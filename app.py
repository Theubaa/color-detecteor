from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from color_detection import detect_colors
import os
from typing import Dict, Any, List
import base64
from io import BytesIO

app = FastAPI(title="Color Detection API")

# Create uploads directory if it doesn't exist
os.makedirs("uploads", exist_ok=True)

@app.get("/", response_class=HTMLResponse)
async def get_upload_page():
    return """
    <!DOCTYPE html>
    <html>
        <head>
            <title>Color Detection</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    max-width: 1200px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #f5f5f5;
                }
                .container {
                    background-color: white;
                    padding: 20px;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }
                h1 {
                    color: #333;
                    text-align: center;
                }
                .upload-form {
                    display: flex;
                    flex-direction: column;
                    gap: 20px;
                    align-items: center;
                }
                .file-input {
                    padding: 10px;
                    border: 2px dashed #ccc;
                    border-radius: 4px;
                    width: 100%;
                    max-width: 400px;
                    display: none;
                }
                .submit-btn {
                    background-color: #4CAF50;
                    color: white;
                    padding: 10px 20px;
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                    font-size: 16px;
                }
                .submit-btn:hover {
                    background-color: #45a049;
                }
                #result {
                    margin-top: 20px;
                    padding: 20px;
                    border-radius: 4px;
                    display: none;
                }
                .color-box {
                    display: inline-block;
                    width: 20px;
                    height: 20px;
                    margin-right: 5px;
                    border: 1px solid #ccc;
                    vertical-align: middle;
                }
                .logo-result {
                    border: 1px solid #ddd;
                    padding: 20px;
                    margin: 20px 0;
                    border-radius: 8px;
                    background-color: white;
                }
                .logo-preview {
                    max-width: 200px;
                    max-height: 200px;
                    margin: 10px 0;
                }
                .colors-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
                    gap: 10px;
                    margin-top: 10px;
                }
                .color-item {
                    display: flex;
                    align-items: center;
                    gap: 5px;
                }
                .drop-zone {
                    border: 2px dashed #ccc;
                    padding: 20px;
                    text-align: center;
                    border-radius: 4px;
                    cursor: pointer;
                    transition: border-color 0.3s ease;
                }
                .drop-zone:hover {
                    border-color: #4CAF50;
                }
                .drop-zone.dragover {
                    border-color: #4CAF50;
                    background-color: #f0f9f0;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Color Detection</h1>
                <form class="upload-form" id="uploadForm">
                    <div class="drop-zone" id="dropZone">
                        <p>Drag and drop up to 100 logo files here or click to select</p>
                        <input type="file" class="file-input" id="fileInput" accept=".png,.svg,.jpg,.jpeg,.ai,.eps" multiple required>
                    </div>
                    <button type="submit" class="submit-btn" id="detectBtn">Detect Colors</button>
                </form>
                <div id="loading" style="display:none; text-align:center; margin-top:20px; font-weight:bold; color:#4CAF50;">Uploading and processing files...</div>
                <div id="result"></div>
            </div>
            <script>
                const dropZone = document.getElementById('dropZone');
                const fileInput = document.getElementById('fileInput');
                const resultDiv = document.getElementById('result');

                // Drag and drop handlers
                dropZone.addEventListener('dragover', (e) => {
                    e.preventDefault();
                    dropZone.classList.add('dragover');
                });

                dropZone.addEventListener('dragleave', () => {
                    dropZone.classList.remove('dragover');
                });

                dropZone.addEventListener('drop', (e) => {
                    e.preventDefault();
                    dropZone.classList.remove('dragover');
                    fileInput.files = e.dataTransfer.files;
                });

                dropZone.addEventListener('click', () => {
                    fileInput.click();
                });

                document.getElementById('uploadForm').onsubmit = async (e) => {
                    e.preventDefault();
                    const detectBtn = document.getElementById('detectBtn');
                    const loadingDiv = document.getElementById('loading');
                    detectBtn.disabled = true;
                    loadingDiv.style.display = 'block';
                    
                    if (!fileInput.files.length) {
                        alert('Please select at least one file');
                        detectBtn.disabled = false;
                        loadingDiv.style.display = 'none';
                        return;
                    }

                    if (fileInput.files.length > 100) {
                        alert('Maximum 100 files allowed');
                        detectBtn.disabled = false;
                        loadingDiv.style.display = 'none';
                        return;
                    }

                    const formData = new FormData();
                    for (let file of fileInput.files) {
                        formData.append('files', file);
                    }

                    try {
                        const response = await fetch('/upload', {
                            method: 'POST',
                            body: formData
                        });
                        if (!response.ok) {
                            const text = await response.text();
                            throw new Error(text || `Upload failed with status ${response.status}`);
                        }
                        const data = await response.json();
                        
                        let resultsHtml = '<h2>Results:</h2>';
                        
                        data.results.forEach(result => {
                            if (result.error) {
                                resultsHtml += `
                                    <div class="logo-result" style="border-color:#f99">
                                        <h3>${result.filename}</h3>
                                        <p style="color:#c00;font-weight:bold;">Error: ${result.error}</p>
                                    </div>
                                `;
                                return;
                            }
                            resultsHtml += `
                                <div class="logo-result">
                                    <h3>${result.filename}</h3>
                                    <img src="${result.preview}" class="logo-preview" alt="${result.filename}">
                                    <p>Total Colors Detected: ${result.count}</p>
                                    <div class="colors-grid">
                                        ${result.colors.map(color => `
                                            <div class="color-item">
                                                <span class="color-box" style="background-color: ${color}"></span>
                                                <span>${color}</span>
                                            </div>
                                        `).join('')}
                                    </div>
                                </div>
                            `;
                        });
                        
                        resultDiv.innerHTML = resultsHtml;
                        resultDiv.style.display = 'block';
                    } catch (error) {
                        alert('Error uploading files: ' + (error?.message || 'Unknown error'));
                        console.error(error);
                    } finally {
                        detectBtn.disabled = false;
                        loadingDiv.style.display = 'none';
                    }
                };
            </script>
        </body>
    </html>
    """

@app.post("/upload")
async def upload_files(files: List[UploadFile] = File(...)) -> Dict[str, Any]:
    results = []
    allowed_exts = {'.png', '.jpg', '.jpeg', '.svg', '.webp', '.bmp', '.tiff', '.tif', '.gif', '.ai', '.eps'}
    
    for file in files:
        # Save the uploaded file temporarily
        file_path = f"uploads/{file.filename}"
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        try:
            # Validate extension early and provide per-file error messages
            ext = os.path.splitext(file.filename)[1].lower()
            if ext not in allowed_exts:
                results.append({
                    "filename": file.filename,
                    "error": f"Unsupported file type '{ext}'. Supported: .png, .jpg, .jpeg, .svg, .webp, .bmp, .tiff, .tif, .gif, .ai, .eps"
                })
                continue

            # Process the file
            count, colors = detect_colors(file_path)
            
            # Determine MIME type and create preview
            ext = os.path.splitext(file.filename)[1].lower()
            preview = None
            
            if ext == '.svg':
                mime = 'image/svg+xml'
            elif ext in ['.jpg', '.jpeg']:
                mime = 'image/jpeg'
            elif ext in ['.ai', '.eps']:
                # For AI/EPS files, convert to PNG for preview
                try:
                    from colordetector import _convert_ai_eps_to_raster
                    temp_png = _convert_ai_eps_to_raster(file_path)
                    with open(temp_png, "rb") as png_file:
                        preview = f"data:image/png;base64," + base64.b64encode(png_file.read()).decode()
                    os.remove(temp_png)
                except Exception as e:
                    # Fallback: use original file if conversion fails
                    mime = 'application/octet-stream'
                    with open(file_path, "rb") as image_file:
                        preview = f"data:{mime};base64," + base64.b64encode(image_file.read()).decode()
            else:
                mime = 'image/png'
            
            # Create preview image (if not already created for AI/EPS)
            if preview is None:
                with open(file_path, "rb") as image_file:
                    preview = f"data:{mime};base64," + base64.b64encode(image_file.read()).decode()
            
            results.append({
                "filename": file.filename,
                "count": count,
                "colors": list(colors),
                "preview": preview
            })
            
        except Exception as e:
            if os.path.exists(file_path):
                os.remove(file_path)
            raise e
        finally:
            # Clean up the temporary file
            if os.path.exists(file_path):
                os.remove(file_path)
    
    return {"results": results}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000) 