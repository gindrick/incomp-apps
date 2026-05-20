přidat do llm_service.py JD pre-processing krok 

– jednou při vytvoření recruitment campaign zavoláš LLM, které z JD vytáhne strukturovaný seznam must-have a nice-to-have požadavků a uložíš to do DB. Pak při hodnocení kandidáta posíláš tento strukturovaný výstup (ne raw JD text) 
– ušetří to tokeny a zlepší konzistenci hodnocení.