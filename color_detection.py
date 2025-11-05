from PIL import Image
import numpy as np
from bs4 import BeautifulSoup
import os
import re
import cv2
from typing import Tuple, Set
import math
import tempfile
import cairosvg

def _to_hex(rgb: np.ndarray) -> str:
    r, g, b = [int(x) for x in rgb]
    return '#{:02X}{:02X}{:02X}'.format(r, g, b)


def _has_alpha(pil_img: Image.Image) -> bool:
    return pil_img.mode in ("LA", "RGBA", "PA")


def _composite_on_white(pil_img: Image.Image) -> Image.Image:
    if pil_img.mode == "RGBA":
        background = Image.new("RGBA", pil_img.size, (255, 255, 255, 255))
        return Image.alpha_composite(background, pil_img).convert("RGB")
    return pil_img.convert("RGB")


def _resize_max(pil_img: Image.Image, max_dim: int = 800) -> Image.Image:
    w, h = pil_img.size
    scale = min(1.0, float(max_dim) / float(max(w, h)))
    if scale < 1.0:
        pil_img = pil_img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return pil_img


def _gray_world_color_constancy(np_rgb: np.ndarray) -> np.ndarray:
    # Scale each channel so its mean equals overall gray mean
    rgb = np_rgb.astype(np.float32) + 1e-6
    means = rgb.reshape(-1, 3).mean(axis=0)
    gray = means.mean()
    scale = gray / means
    corrected = np.clip(rgb * scale, 0, 255)
    return corrected.astype(np.uint8)


def _estimate_k(np_lab: np.ndarray) -> int:
    # Simple heuristic using image entropy to choose K in [3, 8]
    # Compute luminance histogram entropy as a proxy for complexity
    l_channel = np_lab[:, 0]
    hist, _ = np.histogram(l_channel, bins=32, range=(0, 255), density=True)
    hist = hist + 1e-12
    entropy = -np.sum(hist * np.log2(hist))
    # Map entropy roughly 0..5 to 3..8
    k = 3 + int(round((min(max(entropy, 0.0), 5.0) / 5.0) * 5))
    return int(min(max(k, 3), 8))


def _merge_close_lab_colors(centers_lab: np.ndarray, threshold: float = 10.0) -> np.ndarray:
    # Merge LAB centers within CIE76 distance threshold
    kept = []
    for c in centers_lab:
        if not kept:
            kept.append(c)
            continue
        dists = [np.linalg.norm(c - k) for k in kept]
        if min(dists) >= threshold:
            kept.append(c)
    return np.array(kept, dtype=np.float32)


def count_raster_colors(file_path: str) -> Tuple[int, Set[str]]:
    # Open with Pillow (supports most formats); handle alpha; downscale; color constancy
    with Image.open(file_path) as im:
        # For GIFs and multi-frame images, use the first frame
        try:
            im.seek(0)
        except Exception:
            pass
        if _has_alpha(im):
            im = _composite_on_white(im)
        else:
            im = im.convert("RGB")
        im = _resize_max(im, 800)

    np_rgb = np.array(im)
    if np_rgb.ndim != 3 or np_rgb.shape[2] != 3:
        return 0, set()

    # Denoise while preserving edges to stabilize clustering on textures
    np_rgb = cv2.bilateralFilter(np_rgb, d=7, sigmaColor=75, sigmaSpace=75)
    # Color constancy to reduce lighting variation
    np_rgb = _gray_world_color_constancy(np_rgb)

    # Convert to LAB for perceptual clustering
    lab_img = cv2.cvtColor(np_rgb, cv2.COLOR_RGB2LAB)
    pixels_lab = lab_img.reshape((-1, 3)).astype(np.float32)

    # Optional subsample for performance on very large images
    if pixels_lab.shape[0] > 200000:
        idx = np.random.choice(pixels_lab.shape[0], 200000, replace=False)
        sample_lab = pixels_lab[idx]
    else:
        sample_lab = pixels_lab

    # K-means in LAB space with adaptive K
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.5)
    K = _estimate_k(sample_lab)
    K = min(K, max(3, len(sample_lab)))
    _compactness, labels, centers_lab = cv2.kmeans(sample_lab, K, None, criteria, 5, cv2.KMEANS_PP_CENTERS)

    # Merge close centers to avoid near-duplicates
    centers_lab = _merge_close_lab_colors(centers_lab, threshold=8.0)

    # Convert LAB centers back to RGB
    centers_lab_u8 = np.clip(centers_lab, 0, 255).astype(np.uint8)
    centers_lab_u8 = centers_lab_u8.reshape((-1, 1, 3))
    centers_rgb = cv2.cvtColor(centers_lab_u8, cv2.COLOR_Lab2RGB).reshape((-1, 3))

    # Filter out near-white and near-black artifacts and tiny clusters
    result: Set[str] = set()
    for rgb in centers_rgb:
        r, g, b = [int(x) for x in rgb]
        maxc, minc = max(r, g, b), min(r, g, b)
        if maxc > 245 and minc > 245:
            result.add('white')
            continue
        if maxc < 10 and minc < 10:
            # treat near-black as a valid color if it’s dominant; keep as hex
            result.add(_to_hex(rgb))
            continue
        result.add(_to_hex(rgb))

    return len(result), result


def _convert_ai_eps_to_raster(file_path: str) -> str:
    """
    Convert .ai or .eps vector files to PNG raster format for color detection.
    Returns path to temporary PNG file.
    Strategy:
    1. Try PIL directly (works for some EPS files, especially with Ghostscript)
    2. Try converting EPS to SVG-like format then use cairosvg
    3. For AI files, try reading as PDF if they're PDF-based
    """
    temp_png = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
    temp_png_path = temp_png.name
    temp_png.close()
    
    # Method 1: Try PIL directly (best for EPS files with Ghostscript support)
    try:
        with Image.open(file_path) as img:
            # Convert to RGB if needed
            if img.mode != 'RGB':
                if img.mode in ('RGBA', 'LA', 'P'):
                    # Handle transparency
                    if img.mode == 'RGBA':
                        background = Image.new('RGB', img.size, (255, 255, 255))
                        background.paste(img, mask=img.split()[3])  # Use alpha channel as mask
                        img = background
                    else:
                        img = img.convert('RGB')
                else:
                    img = img.convert('RGB')
            
            # Resize if too large (for performance)
            max_size = 2000
            if max(img.size) > max_size:
                ratio = max_size / max(img.size)
                new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                img = img.resize(new_size, Image.LANCZOS)
            
            # Save as PNG
            img.save(temp_png_path, 'PNG', dpi=(300, 300))
            
            # Verify the saved file
            with Image.open(temp_png_path) as test_img:
                test_img.verify()
            
            return temp_png_path
            
    except Exception as e1:
        # Clean up if failed
        if os.path.exists(temp_png_path):
            try:
                os.remove(temp_png_path)
            except:
                pass
        
        # Method 2: For EPS files, try using cairosvg (if it's SVG-compatible)
        # Some EPS files can be converted this way
        try:
            # Check if file starts with SVG-like content or PostScript
            with open(file_path, 'rb') as f:
                header = f.read(100)
                # If it looks like it might work with cairosvg
                if b'%!PS' in header or b'<svg' in header or b'<?xml' in header:
                    try:
                        cairosvg.svg2png(url=file_path, write_to=temp_png_path, 
                                       output_width=2000, output_height=2000)
                        if os.path.exists(temp_png_path) and os.path.getsize(temp_png_path) > 0:
                            with Image.open(temp_png_path) as test_img:
                                test_img.verify()
                            return temp_png_path
                    except:
                        pass
        except Exception as e2:
            pass
        
        # Method 3: Try pdf2image if available (for PDF-based AI files)
        try:
            import pdf2image
            # AI files are often PDF-based
            images = pdf2image.convert_from_path(file_path, dpi=300)
            if images:
                images[0].save(temp_png_path, 'PNG')
                return temp_png_path
        except ImportError:
            pass
        except Exception as e3:
            pass
        
        # If all methods fail, raise a helpful error
        raise ValueError(
            f"Could not convert {file_path} to raster format. "
            f"Please ensure:\n"
            f"1. For EPS files: Ghostscript is installed (required for PIL to read EPS)\n"
            f"2. For AI files: The file is readable (may need to be exported from Illustrator)\n"
            f"Original error: {str(e1)}"
        )


def extract_svg_colors(file_path):
    def is_white(color):
        color = color.strip().lower()
        if color in ['#fff', '#ffffff', '#FFF', '#FFFFFF', 'white']:
            return True
        rgb_match = re.match(r'rgb\s*\(\s*255\s*,\s*255\s*,\s*255\s*\)', color)
        if rgb_match:
            return True
        rgb_pct_match = re.match(r'rgb\s*\(\s*100%\s*,\s*100%\s*,\s*100%\s*\)', color)
        if rgb_pct_match:
            return True
        rgba_match = re.match(r'rgba\s*\(\s*255\s*,\s*255\s*,\s*255\s*,\s*1(\.0*)?\s*\)', color)
        if rgba_match:
            return True
        rgba_pct_match = re.match(r'rgba\s*\(\s*100%\s*,\s*100%\s*,\s*100%\s*,\s*1(\.0*)?\s*\)', color)
        if rgba_pct_match:
            return True
        return False

    def is_visible(tag):
        style = tag.get('style', '')
        if 'display:none' in style or 'visibility:hidden' in style or 'opacity:0' in style:
            return False
        if tag.get('display') == 'none' or tag.get('visibility') == 'hidden' or tag.get('opacity') == '0':
            return False
        return True

    def normalize_color(color):
        color = color.strip().lower()
        if is_white(color):
            return 'white'
        # Hex color
        if color.startswith('#'):
            if len(color) == 4:
                # e.g. #abc -> #aabbcc
                color = '#' + ''.join([c*2 for c in color[1:]])
            return color.upper()
        # rgb/rgba
        rgb_match = re.match(r'rgb\s*\(([^)]+)\)', color)
        if rgb_match:
            parts = rgb_match.group(1).split(',')
            if '%' in parts[0]:
                # rgb(100%,100%,100%)
                vals = [int(float(p.strip().replace('%','')) * 2.55) for p in parts[:3]]
            else:
                vals = [int(float(p.strip())) for p in parts[:3]]
            return '#{:02X}{:02X}{:02X}'.format(*vals)
        # named color
        return color

    with open(file_path, 'r', encoding='utf-8') as file:
        soup = BeautifulSoup(file.read(), 'xml')
    colors = set()
    # 1. Extract visible fill/stroke colors
    for tag in soup.find_all(True):
        if not is_visible(tag):
            continue
        for attr in ['fill', 'stroke']:
            val = tag.get(attr)
            if val and val.strip().lower() not in ['none', 'transparent'] and not val.startswith('url('):
                colors.add(normalize_color(val))
        style = tag.get('style')
        if style:
            for part in style.split(';'):
                if ':' in part:
                    prop, color_val = part.split(':', 1)
                    prop = prop.strip().lower()
                    color_val = color_val.strip()
                    if prop not in ['fill', 'stroke']:
                        continue
                    if color_val.lower() in ['none', 'transparent'] or color_val.startswith('url('):
                        continue
                    colors.add(normalize_color(color_val))
    # 2. Extract gradient stop colors
    for grad in soup.find_all(['linearGradient', 'radialGradient']):
        for stop in grad.find_all('stop'):
            stop_color = stop.get('stop-color')
            if stop_color:
                colors.add(normalize_color(stop_color))
            stop_style = stop.get('style')
            if stop_style:
                # Only add stop-color, ignore stop-opacity, offset, etc.
                for part in stop_style.split(';'):
                    if part.strip().startswith('stop-color:'):
                        color_val = part.split(':',1)[1].strip()
                        colors.add(normalize_color(color_val))
    return len(colors), colors

def detect_colors(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    temp_file = None
    
    try:
        if ext == '.svg':
            return extract_svg_colors(file_path)
        elif ext in ['.ai', '.eps']:
            # Convert vector format to raster first
            temp_file = _convert_ai_eps_to_raster(file_path)
            # Process the converted raster image
            result = count_raster_colors(temp_file)
            return result
        else:
            # All other raster formats handled here: png, jpg/jpeg, webp, bmp, tiff, gif, etc.
            return count_raster_colors(file_path)
    finally:
        # Clean up temporary converted file
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass

if __name__ == "__main__":
    file_path = input("Enter path to image file (any format or .svg): ").strip()
    if not os.path.isfile(file_path):
        print("File not found. Please check the path.")
    else:
        count, colors = detect_colors(file_path)
        print(f"\n✅ Total Colors Detected: {count}")
        print("🎨 Unique Colors List:")
        for color in colors:
            print(color)