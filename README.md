# Color Detection API

FastAPI service to detect dominant/unique colors from uploaded logo/image files (PNG, JPG/JPEG, SVG, WEBP, BMP, TIFF, GIF, AI, EPS). Includes a simple web UI at `/` and a JSON API at `/upload`.

Repository: [`https://github.com/Theubaa/color-detecteor.git`](https://github.com/Theubaa/color-detecteor.git)


## Features
- Upload up to 100 files in one request
- Supports raster formats (PNG/JPG/WEBP/BMP/TIFF/GIF) and vector formats (SVG, AI, EPS)
- Auto-handles alpha/transparency and color-constancy for better clustering
- Returns unique colors as hex codes and a preview of the uploaded image
- Simple HTML drag-and-drop UI at the root path


## API Overview
- `GET /` — Minimal web UI for testing uploads in a browser
- `POST /upload` — Multipart form-data with one or more files under the field name `files`

Example request (curl):

```bash
curl -X POST \
  -F "files=@/path/to/logo1.png" \
  -F "files=@/path/to/logo2.svg" \
  http://YOUR_HOSTNAME_OR_IP/upload
```

Example response (truncated):

```json
{
  "results": [
    {
      "filename": "logo1.png",
      "count": 5,
      "colors": ["#112233", "#AABBCC", "#FF9900", "#000000", "white"],
      "preview": "data:image/png;base64,iVBORw0KGgo..."
    },
    {
      "filename": "logo2.svg",
      "count": 3,
      "colors": ["#123456", "#FEDCBA", "white"],
      "preview": "data:image/svg+xml;base64,PHN2ZyB4bWxucz0..."
    }
  ]
}
```


## Deploy on DigitalOcean (Ubuntu) — Step by Step

These instructions assume a fresh Ubuntu 22.04/24.04 droplet with a user that has sudo privileges.

### 1) Create a Droplet
1. In DigitalOcean, create a Ubuntu droplet (2 GB RAM recommended)
2. Add your SSH key and launch
3. Note the droplet public IP

### 2) Log in and basic setup
```bash
ssh root@YOUR_DROPLET_IP
adduser appuser
usermod -aG sudo appuser
su - appuser
```

Update packages and install base tools:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl build-essential pkg-config
```

### 3) System libraries required by this project
This app uses Pillow, OpenCV, CairoSVG, and optional PDF/AI handling. Install:
```bash
sudo apt install -y \
  python3 python3-venv python3-pip \
  libgl1 libglib2.0-0 \
  libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
  ghostscript poppler-utils
```

- `libgl1 libglib2.0-0` — needed for OpenCV runtime
- `libcairo2 libpango*` — needed for CairoSVG
- `ghostscript poppler-utils` — improves handling for EPS/PDF/AI conversions

### 4) Clone the repository
```bash
git clone https://github.com/Theubaa/color-detecteor.git
cd color-detecteor
```

If a `venv` directory exists in the repo (accidentally committed), DO NOT USE it. Remove it locally to avoid conflicts:
```bash
rm -rf venv*/
```

### 5) Create a virtual environment and install dependencies
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel
pip install -r requirements.txt
```

If `opencv-python` fails to build, try the prebuilt wheel variant or minimal headless package:
```bash
pip install opencv-python==4.9.0.80 || pip install opencv-python-headless==4.9.0.80
```

### 6) Quick test (development server)
```bash
source .venv/bin/activate
uvicorn app:app --host 0.0.0.0 --port 8000 --workers 2
```

Visit: `http://YOUR_DROPLET_IP:8000` and try the upload UI. Press Ctrl+C to stop.

### 7) Create a systemd service (production)
Create a service so the app runs on boot and restarts on failure.

```bash
sudo tee /etc/systemd/system/color-detect.service > /dev/null <<'EOF'
[Unit]
Description=Color Detection API (FastAPI via Uvicorn)
After=network.target

[Service]
User=appuser
Group=appuser
WorkingDirectory=/home/appuser/color-detecteor
Environment="PATH=/home/appuser/color-detecteor/.venv/bin"
ExecStart=/home/appuser/color-detecteor/.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000 --workers 2
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable color-detect.service
sudo systemctl start color-detect.service
sudo systemctl status color-detect.service --no-pager
```

### 8) Set up Nginx reverse proxy (optional but recommended)
```bash
sudo apt install -y nginx

sudo tee /etc/nginx/sites-available/color-detect > /dev/null <<'EOF'
server {
    listen 80;
    server_name YOUR_DOMAIN_OR_IP;

    client_max_body_size 50M; # allow larger uploads if needed

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/color-detect /etc/nginx/sites-enabled/color-detect
sudo nginx -t
sudo systemctl reload nginx
```

Now your API/UI should be reachable on port 80.

### 9) Enable HTTPS with Let’s Encrypt (if you have a domain)
```bash
sudo snap install core; sudo snap refresh core
sudo snap install --classic certbot
sudo ln -s /snap/bin/certbot /usr/bin/certbot
sudo certbot --nginx -d YOUR_DOMAIN
```

### 10) Firewall (UFW)
```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```


## Operational Notes

- File size limits: Nginx default client body size is small; we set `client_max_body_size 50M`. Adjust as needed. Each uploaded file is temporarily stored under `uploads/` during processing and immediately cleaned up.
- Converting AI/EPS: We attempt several strategies; Ghostscript and Poppler help some files. Not all proprietary AI files are convertible; users may need to export to PDF or SVG.
- Workers: Tune `--workers` based on CPU and memory. OpenCV and Pillow use native threads; test under load.
- Logging: Use `journalctl -u color-detect.service -f` to tail logs.
- Updates: To deploy updates:
  ```bash
  cd /home/appuser/color-detecteor
  git pull
  source .venv/bin/activate
  pip install -r requirements.txt --upgrade
  sudo systemctl restart color-detect.service
  ```


## Local Development
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
```

Open `http://127.0.0.1:8000`.


## Housekeeping (recommended)

The repository previously included a committed `venv` which bloats the repo and triggers large-file warnings (e.g., `cv2.pyd`). You should:

1. Add a `.gitignore` to exclude virtual environments and OS files:
   ```
   .venv/
   venv*/
   __pycache__/
   *.pyc
   uploads/
   .DS_Store
   ```
2. Remove any committed `venv` directories and re-commit.
3. If the repo size remains large, consider rewriting history with tools like `git filter-repo` or `git lfs migrate`.


## License
This project has no explicit license. Add one if you intend to share or open-source.


## Reference
- Repository: [`https://github.com/Theubaa/color-detecteor.git`](https://github.com/Theubaa/color-detecteor.git)