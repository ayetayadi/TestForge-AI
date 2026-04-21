"""add placeholder_count to playwright_script_versions

Revision ID: 82fce15fd9b8
Revises: a3c91f2e4d87
Create Date: 2026-04-20 03:49:34.961944

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '82fce15fd9b8'
down_revision: Union[str, Sequence[str], None] = 'a3c91f2e4d87'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Ajouter la colonne placeholder_count
    op.add_column('playwright_script_versions', 
        sa.Column('placeholder_count', sa.Integer(), server_default='0', nullable=False)
    )
    
    # 2. Supprimer la valeur par défaut existante sur source
    op.execute("ALTER TABLE playwright_script_versions ALTER COLUMN source DROP DEFAULT")
    
    # 3. Convertir la colonne source vers le type Enum
    op.execute("""
        ALTER TABLE playwright_script_versions 
        ALTER COLUMN source TYPE scriptsource 
        USING (
            CASE source
                WHEN 'generated' THEN 'V1_DRAFT'::scriptsource
                WHEN 'V2_CORRECTED' THEN 'V2_CORRECTED'::scriptsource
                WHEN 'MANUAL_EDIT' THEN 'MANUAL_EDIT'::scriptsource
                WHEN 'AI_FIX' THEN 'AI_FIX'::scriptsource
                ELSE 'V1_DRAFT'::scriptsource
            END
        )
    """)
    
    # 4. Remettre une valeur par défaut (V1_DRAFT)
    op.execute("ALTER TABLE playwright_script_versions ALTER COLUMN source SET DEFAULT 'V1_DRAFT'::scriptsource")
    
    # 5. S'assurer que la colonne est NOT NULL
    op.alter_column('playwright_script_versions', 'source', nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    # 1. Supprimer la valeur par défaut
    op.execute("ALTER TABLE playwright_script_versions ALTER COLUMN source DROP DEFAULT")
    
    # 2. Reconvertir source vers VARCHAR
    op.execute("""
        ALTER TABLE playwright_script_versions 
        ALTER COLUMN source TYPE VARCHAR(50) 
        USING source::text
    """)
    
    # 3. Remettre l'ancienne valeur par défaut
    op.execute("ALTER TABLE playwright_script_versions ALTER COLUMN source SET DEFAULT 'generated'")
    
    # 4. Supprimer la colonne placeholder_count
    op.drop_column('playwright_script_versions', 'placeholder_count')
    
    # 5. NE PAS supprimer le type (peut être utilisé ailleurs)
    # op.execute("DROP TYPE scriptsource")