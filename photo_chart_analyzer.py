"""Rule-based visual inspection of MT5 chart screenshots. No AI/API calls."""
from __future__ import annotations
import cv2
import numpy as np

def analyze_chart_image(image_bytes: bytes) -> dict:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        return {"status":"WAIT","reason":"تعذر قراءة الصورة؛ أرسل لقطة شاشة واضحة للشارت."}
    h, w = image.shape[:2]
    if h < 180 or w < 240:
        return {"status":"WAIT","reason":"الصورة صغيرة أو غير واضحة؛ أرسل لقطة كاملة للشارت."}

    # Ignore most chart headers, toolbars and bottom time-axis labels.
    y1, y2 = int(h * 0.12), int(h * 0.86)
    x1, x2 = int(w * 0.05), int(w * 0.95)
    roi = image[y1:y2, x1:x2]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    # Common MT5 green/up and red/down candle palettes; other palettes are
    # intentionally treated as unsupported rather than guessed.
    green = cv2.inRange(hsv, np.array([35, 65, 55]), np.array([100, 255, 255]))
    red_a = cv2.inRange(hsv, np.array([0, 70, 55]), np.array([12, 255, 255]))
    red_b = cv2.inRange(hsv, np.array([168, 70, 55]), np.array([179, 255, 255]))
    red = cv2.bitwise_or(red_a, red_b)

    # Remove isolated compression noise.
    kernel = np.ones((2, 2), np.uint8)
    green = cv2.morphologyEx(green, cv2.MORPH_OPEN, kernel)
    red = cv2.morphologyEx(red, cv2.MORPH_OPEN, kernel)
    gy, gx = np.where(green > 0)
    ry, rx = np.where(red > 0)
    green_n, red_n = int(len(gx)), int(len(rx))
    total = green_n + red_n
    if total < 120:
        return {"status":"WAIT","reason":"لم أتعرف بوضوح على شموع خضراء/حمراء. قد تختلف ألوان الشارت أو تكون الصورة غير واضحة."}

    # Estimate only the visible direction of colored candle pixels, not price.
    xs = np.concatenate([gx, rx]).astype(float)
    ys = np.concatenate([gy, ry]).astype(float)
    bins = np.linspace(0, roi.shape[1], 9)
    centers, medians = [], []
    for left, right in zip(bins[:-1], bins[1:]):
        mask = (xs >= left) & (xs < right)
        if int(mask.sum()) >= 8:
            centers.append((left + right) / 2)
            medians.append(float(np.median(ys[mask])))
    slope = float(np.polyfit(centers, medians, 1)[0]) if len(centers) >= 4 else 0.0
    green_share = green_n / total
    red_share = red_n / total

    if slope < -0.035 and green_share >= 0.40:
        bias, status = "ميل بصري صاعد", "UP"
    elif slope > 0.035 and red_share >= 0.40:
        bias, status = "ميل بصري هابط", "DOWN"
    else:
        bias, status = "حركة مختلطة أو غير حاسمة", "WAIT"

    return {
        "status": status,
        "bias": bias,
        "green_pixels": green_n,
        "red_pixels": red_n,
        "green_share": round(green_share * 100, 1),
        "red_share": round(red_share * 100, 1),
        "reason": "قراءة بصرية تقريبية لألوان الشموع وميلها داخل الصورة فقط."
    }
