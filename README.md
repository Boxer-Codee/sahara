# CodeCrafted — Employee Payroll Management System

> Full-stack Django + Neon PostgreSQL payroll system for CodeCrafted Packaging Company.

---

## 🚀 Quick Start (macOS)

### 1. Install Dependencies
```bash
pip3 install -r requirements.txt
```

### 2. Configure Environment
The `.env` file is already configured with your Neon DB. Verify it contains:
```
SECRET_KEY=...
DEBUG=True
DATABASE_URL=postgresql://neondb_owner:...@...neon.tech/neondb?sslmode=require
ALLOWED_HOSTS=localhost,127.0.0.1
```

### 3. Run Migrations
```bash
python3 manage.py migrate
```

### 4. Create Superuser (Admin)
```bash
python3 manage.py createsuperuser
```
Default credentials already created:
- **Username:** `admin`
- **Password:** `admin@123`

### 5. Start Server
```bash
python3 manage.py runserver
```
Visit → **http://127.0.0.1:8000/**

---

## 📁 Project Structure

```
employee/
├── codecrafted/          # Django project config
│   ├── settings.py       # All settings (Neon DB, whitenoise)
│   ├── urls.py           # Root URL config
│   └── wsgi.py
├── payroll/              # Main app
│   ├── models.py         # Employee, WorkHours, AdvancePayment, Salary
│   ├── views.py          # All views (auth, dashboard, CRUD)
│   ├── forms.py          # All forms
│   ├── urls.py           # App URL patterns
├── templates/
│   ├── base.html         # Sidebar layout
│   ├── dashboard.html
│   ├── auth/login.html
│   ├── employees/        # list, form, detail, delete
│   ├── workhours/        # mark, view
│   ├── advance/          # list, form
│   ├── salary/           # list

│   ├── reports/          # report
│   └── managers/         # list, form, delete
├── static/
│   ├── css/style.css     # Full custom stylesheet
│   └── js/main.js        # Sidebar toggle
├── .env                  # Environment variables
├── requirements.txt
├── Procfile              # Render deployment
└── manage.py
```

---

## 🔐 Roles & Permissions

| Feature              | Admin | Manager | Employee |
|----------------------|:-----:|:-------:|:--------:|
| Dashboard            | ✅    | ✅      | ✅       |
| Add/Edit Employees   | ✅    | ✅      | ❌       |
| Delete Employees     | ✅    | ❌      | ❌       |
| Mark Work Hours      | ✅    | ✅      | ❌       |
| Give Advance         | ✅    | ✅      | ❌       |
| Mark Salary Paid     | ✅    | ✅      | ❌       |
| View Reports         | ✅    | ✅      | ❌       |
| Export CSV/Excel     | ✅    | ✅      | ❌       |
| Manage Managers      | ✅    | ❌      | ❌       |

---

## 💰 Salary Calculation

```
Hourly Rate    = Daily Rate ÷ 12
Gross Salary   = Total Hours Worked × Hourly Rate
Final Salary   = Gross Salary − Total Advance
```
- **Salary is Auto-Calculated** — fully automated via Django signals on WorkHours and Advance updates
- Overtime is calculated at the regular hourly rate.
- Maximum 16 hours working per day.
- Once marked as **Paid**, salary cannot be re-calculated or modified.

---

## 📊 Key Features

- **Dashboard** — live stats: total employees, logged hours today, monthly salary
- **Employee Management** — add/edit/delete with auto-generated unique ID (EMP0001)
- **Employee Detail Page** — full profile, work hours history, advance history, salary history
- **Work Hours** — daily 8-16 hour logging interface
- **Advance System** — track cash advance given to employees
- **Salary** — auto-calculated via signals, mark as paid with user + timestamp
- **Reports** — monthly report with CSV + Excel export
- **Manager Accounts** — admin creates/deletes manager accounts
- **Responsive** — sidebar collapses on mobile

---

## 🚀 Deploy on Render + Neon

### Step 1 — Push to GitHub
```bash
git init && git add . && git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/codecrafted-payroll.git
git push -u origin main
```

### Step 2 — Create Render Web Service
1. Go to [render.com](https://render.com) → New → Web Service
2. Connect your GitHub repo
3. Build command: `pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate`
4. Start command: `gunicorn codecrafted.wsgi:application`

### Step 3 — Environment Variables on Render
```
SECRET_KEY       = <generate a strong random key>
DEBUG            = False
DATABASE_URL     = postgresql://neondb_owner:...@...neon.tech/neondb?sslmode=require
ALLOWED_HOSTS    = your-app.onrender.com
```

### Step 4 — Create Superuser on Render
Use Render Shell:
```bash
python manage.py createsuperuser
```

---

## 🗄️ Neon Database

- **Project:** codecrafted-payroll
- **Project ID:** red-mode-05075614
- **Branch:** main (br-quiet-sea-amiixzgp)
- **Database:** neondb
- **Region:** us-east-1

---

## 🛠️ Tech Stack

| Layer      | Technology                        |
|------------|-----------------------------------|
| Backend    | Django 4.2 (MVT pattern)          |
| Database   | Neon PostgreSQL (serverless)       |
| Frontend   | Bootstrap 5 + Custom CSS          |
| Icons      | Bootstrap Icons                   |
| Fonts      | Inter (Google Fonts)              |
| Auth       | Django built-in auth              |
| Export     | openpyxl (Excel), csv (built-in)  |
| Deploy     | Gunicorn + Render + Neon          |
| Static     | WhiteNoise                        |
# sahara
