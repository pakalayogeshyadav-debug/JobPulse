import sys
from pathlib import Path

# Add src to Python path
src_dir = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(src_dir))

from sqlalchemy import create_engine, MetaData
from sqlalchemy.orm import declarative_base
from jobpulse.config.settings import get_settings
from jobpulse.models import Base

def check_drift():
    settings = get_settings()
    engine = create_engine(settings.database_url)
    
    db_metadata = MetaData()
    db_metadata.reflect(bind=engine)
    
    orm_metadata = Base.metadata
    
    print(f"{'ORM Model':<25} {'Database Table':<20} {'Status':<15}")
    print("-" * 65)
    
    all_ok = True
    
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        table = mapper.local_table
        table_name = table.name
        model_name = cls.__name__
        
        if table_name not in db_metadata.tables:
            print(f"{model_name:<25} {table_name:<20} [X] Missing Table")
            all_ok = False
            continue
            
        db_table = db_metadata.tables[table_name]
        
        # Check columns
        orm_columns = set(c.name for c in table.columns)
        db_columns = set(c.name for c in db_table.columns)
        
        missing_in_db = orm_columns - db_columns
        extra_in_db = db_columns - orm_columns
        
        status = "[OK]"
        issues = []
        
        if missing_in_db:
            issues.append(f"Missing in DB: {', '.join(missing_in_db)}")
        if extra_in_db:
            issues.append(f"Extra in DB: {', '.join(extra_in_db)}")
            
        if issues:
            status = "[!] Drift"
            all_ok = False
            
        print(f"{model_name:<25} {table_name:<20} {status}")
        for issue in issues:
            print(f"  |- {issue}")

    if all_ok:
        print("\n[OK] All models match the database schema.")
    else:
        print("\n[!] Schema drift detected.")

if __name__ == "__main__":
    check_drift()
