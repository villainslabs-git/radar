from core.fingerprint import FingerprintEngine

engine = FingerprintEngine()
t1 = "AIF 2026 | AI Festival"
t2 = "AI Film Festival 2026"

nt1 = engine.normalize_title(t1)
nt2 = engine.normalize_title(t2)

sim = engine._title_similarity(nt1, nt2)
print(f"Title 1: '{nt1}'")
print(f"Title 2: '{nt2}'")
print(f"Similarity: {sim}")
