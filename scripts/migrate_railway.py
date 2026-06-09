"""Run this with: railway run python scripts/migrate_railway.py"""
import sqlalchemy as sa
from src.database.models import Base
from src.database.session import get_engine

engine = get_engine()
inspector = sa.inspect(engine)
cols = [c['name'] for c in inspector.get_columns('contact_status')]
print('Existing columns:', cols)

missing = []
if 'comment' not in cols:
    missing.append('comment TEXT')
if 'contact_method' not in cols:
    missing.append('contact_method VARCHAR(50)')
if 'response_received' not in cols:
    missing.append('response_received VARCHAR(30)')
if 'follow_up_date' not in cols:
    missing.append('follow_up_date DATE')
if 'icp_feedback' not in cols:
    missing.append('icp_feedback JSONB')
if 'updated_at' not in cols:
    missing.append('updated_at TIMESTAMP DEFAULT NOW()')

if missing:
    with engine.begin() as conn:
        for col_def in missing:
            col_name = col_def.split()[0]
            conn.execute(sa.text(f'ALTER TABLE contact_status ADD COLUMN IF NOT EXISTS {col_def}'))
            print(f'Added column: {col_def}')
else:
    print('All columns already exist')

# Verify
cols2 = [c['name'] for c in inspector.get_columns('contact_status')]
print('Final columns:', cols2)
