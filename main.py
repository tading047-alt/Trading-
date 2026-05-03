import openpyxl
import os

# Créer le dossier output
os.makedirs("output", exist_ok=True)

# Créer un nouveau classeur
wb = openpyxl.Workbook()
sheet = wb.active
sheet.title = "Tableau"

# Données à écrire (ligne 1 = en-têtes)
data = [
    ["Nom", "Age", "Note", "Ville"],
    ["Ahmed", 22, 15, "Casablanca"],
    ["Sara", 21, 17, "Rabat"],
    ["Youssef", 23, 14, "Marrakech"],
    ["Fatima", 20, 18, "Fès"],
    ["Omar", 24, 16, "Tanger"]
]

# Écrire les données dans la feuille
for row in data:
    sheet.append(row)

# Sauvegarder le fichier
wb.save("output/tableau.xlsx")
print("Tableau enregistré avec succès dans output/tableau.xlsx")
