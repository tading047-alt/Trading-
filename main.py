# ton_script.py
import pandas as pd
import os
import sqlite3  # Bibliothèque standard, pas besoin de l'installer

# Créer le dossier output
os.makedirs("output", exist_ok=True)

# Générer le tableau
data = {
    "Nom": ["Ahmed", "Sara", "Youssef"],
    "Age": [22, 21, 23],
    "Score": [85.5, 92.0, 78.5]
}

df = pd.DataFrame(data)
df.to_excel("output/resultat.xlsx", index=False)
print("Fichier Excel créé avec succès !")
