# BESCOM GridGuard AI — Karnataka ESCOM Electricity Theft Detection

Full-stack AI anomaly detection and vigilance platform for Karnataka ESCOMs (BESCOM, MESCOM, HESCOM, CESC, GESCOM), organized with a decoupled **Flask + MongoDB + Hybrid ML backend** (`backend/`) and **React + Vite + Tailwind CSS frontend** (`frontend/`).

## Project Structure

```text
electricity-theft-detection/
├── backend/
│   ├── app.py                        # Pure Flask REST API (:5000)
│   ├── database.py                   # MongoDB Atlas CRUD & aggregations
│   ├── prepare_data.py               # 8 behavioral features & MongoDB seeding
│   ├── train.py                      # Isolation Forest + Random Forest + SHAP
│   ├── requirements.txt
│   ├── .env.example
│   ├── electricity_bill_dataset.csv
│   ├── data/
│   └── models/
└── frontend/
    ├── package.json
    ├── vite.config.js                # Proxies /api -> http://127.0.0.1:5000
    ├── .env.example
    ├── index.html
    └── src/
        ├── api.js
        ├── App.jsx
        └── components/
```

## Setup & Running

### 1. Backend (`backend/`)
1. Create `backend/.env` from `backend/.env.example` and set your `MONGO_URI`.
2. Activate `venv` and run the data/training pipeline (first time only):
   ```powershell
   .\venv\Scripts\python.exe backend\prepare_data.py
   .\venv\Scripts\python.exe backend\train.py
   ```
3. Start the Flask API server:
   ```powershell
   .\venv\Scripts\python.exe backend\app.py
   ```
   API runs at **http://127.0.0.1:5000**.

### 2. Frontend (`frontend/`)
1. Install dependencies (first time only) and start Vite dev server:
   ```powershell
   cd frontend
   npm install
   npm run dev
   ```
   Dashboard runs at **http://localhost:5173** and proxies `/api/*` requests to `http://127.0.0.1:5000`.
