import os
import json
import sqlite3
import subprocess
import tempfile
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional

from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.utils.logger import setup_logger

# Default batch size if we can't import from app_configs
try:
    from onyx.configs.app_configs import INDEX_BATCH_SIZE
except ImportError:
    INDEX_BATCH_SIZE = 100

logger = setup_logger()


class TallyConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        tally_host: str = "localhost",
        tally_port: int = 9000,
        company_db: Optional[str] = None,
        data_types: Optional[list[str]] = None,
        sync_mode: str = "incremental",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        batch_size: int = INDEX_BATCH_SIZE,
        **kwargs
    ) -> None:
        self.tally_host = tally_host
        self.tally_port = tally_port
        self.company_db = company_db or ""
        self.data_types = data_types or ["vouchers", "ledgers"]
        self.sync_mode = sync_mode
        self.from_date = from_date
        self.to_date = to_date
        self.batch_size = batch_size
        
        # Path to tally-database-loader (current directory contains the loader files)
        self.tally_loader_path = Path(__file__).parent
        # Check if the loader files exist
        if not (self.tally_loader_path / "src" / "index.mts").exists():
            logger.warning(f"Tally loader files not found in: {self.tally_loader_path}")
        self.temp_db_path = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        return credentials

    def _run_tally_sync(self) -> bool:
        """Run the tally-database-loader to sync data"""
        try:
            # Create temporary database file
            self.temp_db_path = tempfile.mktemp(suffix=".db")
            
            # Build command to run tally loader
            cmd = [
                "node", "--loader", "ts-node/esm",
                str(self.tally_loader_path / "src" / "index.mts")
            ]
            
            # Add command line arguments for configuration
            if self.tally_host != "localhost":
                cmd.extend(["--tally-server", self.tally_host])
            if self.tally_port != 9000:
                cmd.extend(["--tally-port", str(self.tally_port)])
            if self.company_db:
                cmd.extend(["--tally-company", self.company_db])
            if self.sync_mode:
                cmd.extend(["--tally-sync", self.sync_mode])
            if self.from_date:
                cmd.extend(["--tally-fromdate", self.from_date])
            if self.to_date:
                cmd.extend(["--tally-todate", self.to_date])
            
            # Set database configuration via environment
            env = os.environ.copy()
            env["DATABASE_ENGINE"] = "sqlite"
            env["DATABASE_FILENAME"] = self.temp_db_path
            
            logger.info(f"Running Tally sync: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                cwd=self.tally_loader_path,
                capture_output=True,
                text=True,
                timeout=3600,  # 1 hour timeout
                env=env
            )
            
            if result.returncode != 0:
                logger.error(f"Tally sync failed: {result.stderr}")
                return False
            
            logger.info("Tally sync completed successfully")
            return True
            
        except subprocess.TimeoutExpired:
            logger.error("Tally sync timed out")
            return False
        except Exception as e:
            logger.error(f"Failed to run Tally sync: {e}")
            return False

    def _extract_documents_from_db(self) -> GenerateDocumentsOutput:
        """Extract documents from the synced SQLite database"""
        if not self.temp_db_path or not Path(self.temp_db_path).exists():
            logger.warning("No temporary database found")
            return

        conn = sqlite3.connect(self.temp_db_path)
        conn.row_factory = sqlite3.Row
        
        try:
            # Extract vouchers
            if "vouchers" in self.data_types:
                yield from self._extract_voucher_documents(conn)
            
            # Extract ledgers
            if "ledgers" in self.data_types:
                yield from self._extract_ledger_documents(conn)
            
            # Extract groups
            if "groups" in self.data_types:
                yield from self._extract_group_documents(conn)
                
        finally:
            conn.close()

    def _extract_voucher_documents(self, conn) -> Generator[list[Document], None, None]:
        """Extract voucher documents from database"""
        try:
            cursor = conn.execute("""
                SELECT 
                    guid,
                    voucher_type_name,
                    voucher_number,
                    reference_number,
                    voucher_date,
                    narration,
                    amount
                FROM trn_voucher
                ORDER BY voucher_date DESC
                LIMIT 1000
            """)
            
            batch = []
            for row in cursor:
                doc_id = f"tally_voucher_{row['guid']}"
                
                content = f"""Voucher: {row['voucher_type_name']} - {row['voucher_number']}
Date: {row['voucher_date']}
Reference: {row['reference_number'] or 'N/A'}
Amount: {row['amount'] or 0}
Narration: {row['narration'] or 'N/A'}
Company: {self.company_db}"""
                
                doc = Document(
                    id=doc_id,
                    sections=[TextSection(text=content)],
                    source=DocumentSource.TALLY,
                    semantic_identifier=f"{row['voucher_type_name']} - {row['voucher_number']}",
                    metadata={
                        "type": "voucher",
                        "voucher_type": str(row['voucher_type_name'] or ''),
                        "date": str(row['voucher_date'] or ''),
                        "amount": str(row['amount'] or '0'),
                        "company": str(self.company_db),
                    }
                )
                
                batch.append(doc)
                
                if len(batch) >= self.batch_size:
                    yield batch
                    batch = []
            
            if batch:
                yield batch
                
        except Exception as e:
            logger.error(f"Error extracting voucher documents: {e}")

    def _extract_ledger_documents(self, conn) -> Generator[list[Document], None, None]:
        """Extract ledger documents from database"""
        try:
            cursor = conn.execute("""
                SELECT 
                    guid,
                    name,
                    parent,
                    alias,
                    opening_balance,
                    closing_balance
                FROM mst_ledger
                ORDER BY name
            """)
            
            batch = []
            for row in cursor:
                doc_id = f"tally_ledger_{row['guid']}"
                
                content = f"""Ledger: {row['name']}
Parent Group: {row['parent'] or 'None'}
Alias: {row['alias'] or 'N/A'}
Opening Balance: {row['opening_balance'] or 0}
Closing Balance: {row['closing_balance'] or 0}
Company: {self.company_db}"""
                
                doc = Document(
                    id=doc_id,
                    sections=[TextSection(text=content)],
                    source=DocumentSource.TALLY,
                    semantic_identifier=str(row['name']),
                    metadata={
                        "type": "ledger",
                        "group": str(row['parent'] or ''),
                        "balance": str(row['closing_balance'] or '0'),
                        "company": str(self.company_db),
                    }
                )
                
                batch.append(doc)
                
                if len(batch) >= self.batch_size:
                    yield batch
                    batch = []
            
            if batch:
                yield batch
                
        except Exception as e:
            logger.error(f"Error extracting ledger documents: {e}")

    def _extract_group_documents(self, conn) -> Generator[list[Document], None, None]:
        """Extract group documents from database"""
        try:
            cursor = conn.execute("""
                SELECT 
                    guid,
                    name,
                    parent,
                    primary_group,
                    is_revenue,
                    is_deemedpositive
                FROM mst_group
                ORDER BY name
            """)
            
            batch = []
            for row in cursor:
                doc_id = f"tally_group_{row['guid']}"
                
                content = f"""Group: {row['name']}
Parent: {row['parent'] or 'Root'}
Primary Group: {row['primary_group'] or 'N/A'}
Is Revenue: {row['is_revenue'] or False}
Is Deemed Positive: {row['is_deemedpositive'] or False}
Company: {self.company_db}"""
                
                doc = Document(
                    id=doc_id,
                    sections=[TextSection(text=content)],
                    source=DocumentSource.TALLY,
                    semantic_identifier=str(row['name']),
                    metadata={
                        "type": "group",
                        "parent": str(row['parent'] or ''),
                        "primary_group": str(row['primary_group'] or ''),
                        "company": str(self.company_db),
                    }
                )
                
                batch.append(doc)
                
                if len(batch) >= self.batch_size:
                    yield batch
                    batch = []
            
            if batch:
                yield batch
                
        except Exception as e:
            logger.error(f"Error extracting group documents: {e}")

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Full load of Tally data"""
        logger.info("Starting full load from Tally")
        
        if not self._run_tally_sync():
            logger.error("Failed to sync data from Tally")
            return
        
        yield from self._extract_documents_from_db()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        """Incremental sync of Tally data"""
        logger.info(f"Starting incremental sync from Tally (start: {start}, end: {end})")
        
        # Convert timestamps to dates for Tally
        start_date = datetime.fromtimestamp(start).strftime("%Y-%m-%d") if start else None
        end_date = datetime.fromtimestamp(end).strftime("%Y-%m-%d") if end else None
        
        # Store original date settings
        original_from_date = self.from_date
        original_to_date = self.to_date
        original_sync_mode = self.sync_mode
        
        try:
            # Set date range for incremental sync
            self.from_date = start_date
            self.to_date = end_date
            self.sync_mode = "incremental"
            
            if not self._run_tally_sync():
                logger.error("Failed to sync data from Tally")
                return
            
            yield from self._extract_documents_from_db()
            
        finally:
            # Restore original settings
            self.from_date = original_from_date
            self.to_date = original_to_date
            self.sync_mode = original_sync_mode

    def validate_connector_settings(self) -> None:
        """Validate Tally connector settings"""
        # Check if Node.js is available
        try:
            result = subprocess.run(
                ["node", "--version"], 
                check=True, 
                capture_output=True,
                text=True
            )
            logger.info(f"Node.js version: {result.stdout.strip()}")
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("Node.js not found. It will be required for actual sync operations.")
            # Don't fail validation for initial setup
            return

        # Check if tally-database-loader exists and dependencies are installed
        if not self.tally_loader_path.exists():
            logger.warning(f"Tally database loader not found at {self.tally_loader_path}")
            # Don't fail validation for initial setup
            return

        if not (self.tally_loader_path / "node_modules").exists():
            logger.warning("Tally loader dependencies not installed. Run 'npm install' in the tally directory.")
            # Don't fail validation for initial setup
            return

        # Test Tally XML server connection (optional for initial setup)
        try:
            response = requests.get(
                f"http://{self.tally_host}:{self.tally_port}",
                timeout=5
            )
            if response.status_code == 200:
                logger.info("Successfully connected to Tally XML server")
            else:
                logger.warning(f"Tally XML server returned status {response.status_code}")
        except requests.exceptions.ConnectionError:
            logger.warning(
                f"Cannot connect to Tally XML server at {self.tally_host}:{self.tally_port}. "
                "Ensure Tally is running with XML server enabled before sync operations."
            )
        except requests.exceptions.Timeout:
            logger.warning("Timeout connecting to Tally XML server. Check server status.")
        except Exception as e:
            logger.warning(f"Error testing Tally connection: {e}")


if __name__ == "__main__":
    # Test the connector
    connector = TallyConnector(
        company_name="Test Company",
        data_types=["vouchers", "ledgers"]
    )
    
    # Test validation
    connector.validate_connector_settings()
    
    # Test document generation
    documents = list(connector.load_from_state())
    print(f"Generated {len(documents)} document batches")