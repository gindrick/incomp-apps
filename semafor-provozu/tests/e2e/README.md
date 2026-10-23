# Testy v prohlížeči

Proti běžícímu vývojovému serveru (`SEMAFOR_ENVIRONMENT=development`, `SEMAFOR_AUTH_MODE=dev`; jinde server vývojové přihlášení odmítne spustit).

```powershell
npm install playwright@1.56.0; npx playwright install chromium
# server: SEMAFOR_AUTH_MODE=dev, SEMAFOR_PUBLIC_URL=http://127.0.0.1:8765/semafor, data z importu zálohy,
# SEMAFOR_DEV_USERS s uživateli jan (správce, jan.kratky@hranipex.com), bob (uživatel), cyril (čtenář)
$env:SEMAFOR_E2E_URL="http://127.0.0.1:8765/semafor"
node tests/e2e/smoke.cjs   # API, pravidla, živé změny, zámek
node tests/e2e/ui.cjs      # rychlé zadání, kanban u druhého uživatele, zámek detailu, příloha, charter PDF
```

Vzor `SEMAFOR_DEV_USERS`:
`{"jan":{"id":"dev-jan","email":"jan.kratky@hranipex.com","name":"Jan Kratky","roles":["Semafor.Admin"]},"bob":{"id":"dev-bob","email":"bob@hranipex.com","name":"Bob Zkušební","roles":["Semafor.User"]},"cyril":{"id":"dev-cyril","email":"cyril@hranipex.com","name":"Cyril Čtenář","roles":["Semafor.Reader"]}}`
