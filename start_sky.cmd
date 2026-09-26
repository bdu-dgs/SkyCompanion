@echo off
set KMP_DUPLICATE_LIB_OK=TRUE
python "%~dp0sky_companion.py" --display %*
