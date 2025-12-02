import sys
import os

# Simple test without dependencies
def test_coda_files():
    print("Testing Coda Connector Files...")
    print("=" * 50)
    
    # Test 1: Check if our files exist
    files_to_check = [
        "backend/onyx/configs/constants.py",
        "backend/onyx/connectors/registry.py", 
        "backend/onyx/connectors/coda/__init__.py",
        "backend/onyx/connectors/coda/coda_connector.py",
        "web/src/components/admin/connectors/CodaConnector.tsx"
    ]
    
    all_exist = True
    for file_path in files_to_check:
        exists = os.path.exists(file_path)
        print(f"✅ {file_path}: {'EXISTS' if exists else '❌ MISSING'}")
        if not exists:
            all_exist = False
    
    # Test 2: Check if CODA is in constants.py
    try:
        with open("backend/onyx/configs/constants.py", "r") as f:
            constants_content = f.read()
            has_coda_enum = 'CODA = "coda"' in constants_content
            has_coda_description = 'DocumentSource.CODA:' in constants_content
            
        print(f"\n📋 constants.py checks:")
        print(f"   CODA enum: {'✅ FOUND' if has_coda_enum else '❌ MISSING'}")
        print(f"   CODA description: {'✅ FOUND' if has_coda_description else '❌ MISSING'}")
        
    except Exception as e:
        print(f"❌ Error reading constants.py: {e}")
        has_coda_enum = has_coda_description = False
    
    # Test 3: Check if CODA is in registry.py
    try:
        with open("backend/onyx/connectors/registry.py", "r") as f:
            registry_content = f.read()
            has_coda_mapping = 'DocumentSource.CODA:' in registry_content
            has_coda_connector = 'onyx.connectors.coda.coda_connector' in registry_content
            
        print(f"\n📋 registry.py checks:")
        print(f"   CODA mapping: {'✅ FOUND' if has_coda_mapping else '❌ MISSING'}")
        print(f"   CODA connector path: {'✅ FOUND' if has_coda_connector else '❌ MISSING'}")
        
    except Exception as e:
        print(f"❌ Error reading registry.py: {e}")
        has_coda_mapping = has_coda_connector = False
    
    # Test 4: Check connector file structure
    try:
        with open("backend/onyx/connectors/coda/coda_connector.py", "r") as f:
            connector_content = f.read()
            has_class = 'class CodaConnector' in connector_content
            has_load_credentials = 'def load_credentials' in connector_content
            has_load_from_state = 'def load_from_state' in connector_content
            
        print(f"\n📋 coda_connector.py checks:")
        print(f"   CodaConnector class: {'✅ FOUND' if has_class else '❌ MISSING'}")
        print(f"   load_credentials method: {'✅ FOUND' if has_load_credentials else '❌ MISSING'}")
        print(f"   load_from_state method: {'✅ FOUND' if has_load_from_state else '❌ MISSING'}")
        
    except Exception as e:
        print(f"❌ Error reading coda_connector.py: {e}")
        has_class = has_load_credentials = has_load_from_state = False
    
    # Final result
    backend_ready = (all_exist and has_coda_enum and has_coda_description and 
                    has_coda_mapping and has_coda_connector and has_class and 
                    has_load_credentials and has_load_from_state)
    
    print(f"\n{'='*50}")
    if backend_ready:
        print("🎉 SUCCESS: Coda connector backend is ready!")
        print("✅ All files exist and contain required code")
        print("✅ Ready to create PR and demo video!")
    else:
        print("❌ ISSUES: Some components are missing")
        
    return backend_ready

if __name__ == "__main__":
    test_coda_files()