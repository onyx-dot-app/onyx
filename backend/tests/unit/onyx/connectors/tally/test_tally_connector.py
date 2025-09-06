"""Unit tests for Tally connector."""

import unittest
from unittest.mock import Mock, patch, MagicMock
import sqlite3
import tempfile
import os
from typing import Any, Dict

from onyx.connectors.tally.connector import TallyConnector
from onyx.connectors.models import Document, DocumentSource


class TestTallyConnector(unittest.TestCase):
    """Test cases for TallyConnector."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = {
            "tally_host": "localhost",
            "tally_port": 9000,
            "company_db": "test_company",
            "sync_mode": "full",
            "batch_size": 100,
            "loader_path": "/test/path"
        }
        self.connector = TallyConnector(**self.config)

    def test_connector_initialization(self):
        """Test TallyConnector initialization."""
        self.assertEqual(self.connector.tally_host, "localhost")
        self.assertEqual(self.connector.tally_port, 9000)
        self.assertEqual(self.connector.company_db, "test_company")
        self.assertEqual(self.connector.sync_mode, "full")
        self.assertEqual(self.connector.batch_size, 100)

    def test_default_values(self):
        """Test TallyConnector with default values."""
        connector = TallyConnector()
        self.assertEqual(connector.tally_host, "localhost")
        self.assertEqual(connector.tally_port, 9000)
        self.assertIsNone(connector.company_db)
        self.assertEqual(connector.sync_mode, "incremental")
        self.assertEqual(connector.batch_size, 100)

    @patch('subprocess.run')
    def test_run_tally_loader_success(self, mock_run):
        """Test successful Tally loader execution."""
        mock_run.return_value = Mock(returncode=0, stdout="Success", stderr="")
        
        result = self.connector._run_tally_loader("test_config.yaml", "test_output.db")
        
        self.assertTrue(result)
        mock_run.assert_called_once()

    @patch('subprocess.run')
    def test_run_tally_loader_failure(self, mock_run):
        """Test failed Tally loader execution."""
        mock_run.return_value = Mock(returncode=1, stdout="", stderr="Error")
        
        result = self.connector._run_tally_loader("test_config.yaml", "test_output.db")
        
        self.assertFalse(result)

    def test_create_sqlite_tables(self):
        """Test SQLite table creation."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp_file:
            db_path = tmp_file.name
        
        try:
            self.connector._create_sqlite_tables(db_path)
            
            # Verify tables exist
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            expected_tables = ['vouchers', 'ledgers', 'groups']
            for table in expected_tables:
                self.assertIn(table, tables)
            
            conn.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    @patch.object(TallyConnector, '_run_tally_loader')
    @patch.object(TallyConnector, '_create_sqlite_tables')
    def test_extract_data_from_tally_success(self, mock_create_tables, mock_run_loader):
        """Test successful data extraction from Tally."""
        mock_run_loader.return_value = True
        
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp_file:
            db_path = tmp_file.name
        
        try:
            result_db_path = self.connector._extract_data_from_tally()
            self.assertIsNotNone(result_db_path)
            mock_run_loader.assert_called_once()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_process_sqlite_data(self):
        """Test processing SQLite data into documents."""
        # Create test database
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp_file:
            db_path = tmp_file.name
        
        try:
            # Create tables and insert test data
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE vouchers (
                    id INTEGER PRIMARY KEY,
                    date TEXT,
                    voucher_type TEXT,
                    voucher_number TEXT,
                    party_name TEXT,
                    amount REAL,
                    narration TEXT
                )
            ''')
            
            cursor.execute('''
                INSERT INTO vouchers 
                (date, voucher_type, voucher_number, party_name, amount, narration)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', ('2024-01-01', 'Sales', 'S001', 'Customer A', 1000.0, 'Test sale'))
            
            conn.commit()
            conn.close()
            
            # Process data
            documents = list(self.connector._process_sqlite_data(db_path))
            
            self.assertGreater(len(documents), 0)
            
            # Check first document
            doc = documents[0]
            self.assertIsInstance(doc, Document)
            self.assertEqual(doc.source, DocumentSource.TALLY)
            self.assertIn('Sales', doc.semantic_identifier)
            
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_validate_connector_settings(self):
        """Test connector settings validation."""
        # Should not raise exception with valid settings
        try:
            self.connector.validate_connector_settings()
        except Exception as e:
            self.fail(f"validate_connector_settings raised {type(e).__name__} unexpectedly!")

    @patch.object(TallyConnector, '_extract_data_from_tally')
    @patch.object(TallyConnector, '_process_sqlite_data')
    def test_load_credentials(self, mock_process_data, mock_extract_data):
        """Test load_credentials method."""
        # This connector doesn't require credentials
        result = self.connector.load_credentials({})
        self.assertIsNone(result)

    @patch.object(TallyConnector, '_extract_data_from_tally')
    @patch.object(TallyConnector, '_process_sqlite_data')
    def test_poll_source(self, mock_process_data, mock_extract_data):
        """Test poll_source method."""
        mock_extract_data.return_value = "/tmp/test.db"
        mock_process_data.return_value = [
            Document(
                id="test_doc_1",
                sections=[],
                source=DocumentSource.TALLY,
                semantic_identifier="Test Document",
                metadata={}
            )
        ]
        
        documents = list(self.connector.poll_source(start=None, end=None))
        
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].id, "test_doc_1")
        mock_extract_data.assert_called_once()
        mock_process_data.assert_called_once_with("/tmp/test.db")


if __name__ == '__main__':
    unittest.main()
