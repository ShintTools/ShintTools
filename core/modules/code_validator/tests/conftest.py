import sys
from pathlib import Path

# Add code_validator root to Python path so that
# imports like 'from rules.blueprint_rules import ...'
# work correctly when running pytest
sys.path.insert(0, str(Path(__file__).parent.parent))
