import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds = Credentials.from_service_account_file(
    "credentials.json",
    scopes=SCOPES
)

client = gspread.authorize(creds)

sheet = client.open_by_key("1RAWDvovHZZ7mEj9A0soo2XnPOudVadxu8KuZeQaR-dM").sheet1

data = sheet.get_all_records()
df = pd.DataFrame(data)

print(df.head())
