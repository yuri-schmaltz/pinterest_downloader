import re

def test_regex():
    html_with_video = '<meta property="og:video:secure_url" content="https://v1.pinimg.com/videos/720p/fb/1a/2b/fb1a2b...mp4">'
    html_with_image = '<meta property="og:image" content="https://i.pinimg.com/736x/ab/cd/ef/abcdef...jpg">'
    
    # Simular lógica do fetch_pin_media
    def extract(text):
        m = re.search(r'<meta[^>]+property=["\']og:video:secure_url["\'][^>]+content=["\']([^"\']+)', text, re.I)
        if not m:
            m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:video:secure_url["\']', text, re.I)
        if not m:
            m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', text, re.I)
        if not m:
            m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', text, re.I)
        return m.group(1) if m else None

    video_url = extract(html_with_video)
    image_url = extract(html_with_image)
    
    print(f"Video detected: {video_url}")
    print(f"Image detected: {image_url}")
    
    assert video_url == "https://v1.pinimg.com/videos/720p/fb/1a/2b/fb1a2b...mp4"
    assert image_url == "https://i.pinimg.com/736x/ab/cd/ef/abcdef...jpg"
    print("Regex tests PASSED")

if __name__ == "__main__":
    test_regex()
