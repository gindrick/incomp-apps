# PowerPoint nástroje (mimo aplikaci)

Charter projektu a přehled pro CEO jako PPTX ve firemní šabloně. Převzato beze změny logiky ze složky
`semafor-skripty` (jediná úprava: `hx.py` hledá šablonu vedle sebe, ne v aktuální složce).

```powershell
pip install python-pptx==1.0.2 lxml
# snímek dat ze serveru (projekty, úkoly, historie jako soubory JSON)
python -m semafor export C:\temp\snimek --snapshot-dir
python tools\pptx\charter_lib.py C:\temp\snimek <id projektu> charter.pptx
python tools\pptx\build_ceo_deck.py C:\temp\snimek prehled-ceo.pptx
```

Ověřeno nad migrovanými daty (19. 10. 2026): charter 2 snímky, přehled CEO 15 snímků / 6 projektů.
