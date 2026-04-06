import yt_dlp

opts = {
    'js_runtimes': {
        'node': {}
    },
    'quiet': True,
    'format': 'best',
    'outtmpl': 'test_download.mp4'
}

print("Running test download with js_runtimes={'node': {}}...")
try:
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info("https://www.youtube.com/watch?v=dQw4w9WgXcQ", download=False)
        print("Success! Title:", info.get('title'))
except Exception as e:
    print("Error:", e)
