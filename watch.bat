@echo off
rem Category Analyzer - tryb watch bez konca. Jesli program sie wylaczy (blad, brak sieci), startuje ponownie po 60 s.
rem Skrot do tego pliku w autostarcie (Win+R -> shell:startup) = start po restarcie Windows.
cd /d %~dp0
:loop
python -m analyzer watch
echo [%date% %time%] analyzer zakonczyl dzialanie - ponowny start za 60 s (Ctrl+C, aby przerwac)
timeout /t 60 /nobreak >nul
goto loop
