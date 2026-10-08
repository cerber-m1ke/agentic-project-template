@echo off
rem Creates an Agentic Project from this template, in place (see setup\INIT.md):
rem   init.cmd --name NAME --language ru --profile software --agents claude,codex --yes
rem The last line must stay one line that ends with the exit /b command: init deletes this
rem file while it runs, and cmd.exe re-reads batch files from disk.
setlocal EnableExtensions DisableDelayedExpansion
for %%I in ("%~dp0.") do set "TB_ROOT=%%~fI"
call "%TB_ROOT%\payload\modules\core\Toolbox\tb.cmd" run "%TB_ROOT%\setup\init.py" %* & exit /b
