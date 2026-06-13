# -*- coding: utf-8 -*-
# Exclude standalone DC scripts (test_dc_*.py) — they have module-level sys.exit
# and are run directly as scripts, not as pytest test cases.
collect_ignore = ["test_dc_data.py", "test_dc_stock.py", "test_dc_ui.py"]
