from nudenet import NudeDetector
from PIL import Image, ImageFilter


LABEL_SEVERITY = {
    "FEMALE_GENITALIA_COVERED": 1,
    "FACE_FEMALE": 0,
    "BUTTOCKS_EXPOSED": 1,
    "FEMALE_BREAST_EXPOSED": 2,
    "FEMALE_GENITALIA_EXPOSED": 2,
    "MALE_BREAST_EXPOSED": 0,
    "ANUS_EXPOSED": 2,
    "FEET_EXPOSED": 0,
    "BELLY_COVERED": 0,
    "FEET_COVERED": 0,
    "ARMPITS_COVERED": 0,
    "ARMPITS_EXPOSED": 0,
    "FACE_MALE": 0,
    "BELLY_EXPOSED": 1,
    "MALE_GENITALIA_EXPOSED": 2,
    "ANUS_COVERED": 2,
    "FEMALE_BREAST_COVERED": 1,
    "BUTTOCKS_COVERED": 1,
}

detector = NudeDetector()


def apply_nsfw_filter(image_path, filter_settings):
    level = filter_settings["level"]
    probability = filter_settings["probability"]
    min_blur = filter_settings["gaussian_blur_minimum"]
    blur_frac = filter_settings["gaussian_blur_fraction"]
    blur_enabled = filter_settings["blur"]

    result = detector.detect(image_path)

    filtered = [
        r
        for r in result
        if r.get("score", 0.0) >= probability
        and LABEL_SEVERITY.get(r["class"], 0) > 0
    ]

    severities = [LABEL_SEVERITY[r["class"]] for r in filtered]
    max_severity = max(severities) if severities else 0
    labels_triggered = sorted({r["class"] for r in filtered})

    if blur_enabled and level > 0 and max_severity >= level:
        img = Image.open(image_path)
        radius = max(min_blur, max(img.size) * blur_frac)
        img = img.filter(ImageFilter.GaussianBlur(radius=radius))
        img.save(image_path)

    return max_severity, labels_triggered
