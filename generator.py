import os
import re
import json
import random
import datetime  
import asyncio
import requests
import traceback
import subprocess  
from collections import Counter
from bs4 import BeautifulSoup
import numpy as np
from PIL import Image, ImageFilter
from duckduckgo_search import DDGS
import feedparser
import edge_tts

try:
    from moviepy import ImageClip, AudioFileClip, CompositeVideoClip
    from moviepy.video.fx import CrossFadeIn
    MOVIEPY_V2 = True
except ImportError:
    from moviepy.editor import ImageClip, AudioFileClip, CompositeVideoClip
    MOVIEPY_V2 = False

# ডাকডাকগো এবং উইকিমিডিয়া ব্লক খেলে হাই-কোয়ালিটি ভিডিও সচল রাখার আল্ট্রা-এইচডি স্পোর্টস ব্যাকড্রপস
GENERIC_SPORTS_FALLBACKS = [
    "https://images.unsplash.com/photo-1546519638-68e109498ffc?w=1920&q=80",  # Basketball Court
    "https://images.unsplash.com/photo-1519766304817-4f37bda74a27?w=1920&q=80",  # Stadium Lights
    "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?w=1920&q=80",  # Sports ball
    "https://images.unsplash.com/photo-1461896836934-ffe607ba8211?w=1920&q=80",  # Running track
    "https://images.unsplash.com/photo-1517649763962-0c623066013b?w=1920&q=80",  # Sports stadium
]

async def generate_voice_and_subtitles(text, voice, audio_path, srt_path):
    communicate = edge_tts.Communicate(text, voice)
    submaker = edge_tts.SubMaker()
    with open(audio_path, "wb") as fobj:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                fobj.write(chunk["data"])
            elif chunk["type"] == "SentenceBoundary":
                submaker.feed(chunk)
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(submaker.get_srt())

def scrape_article(url):
    """ওয়েবসাইট থেকে আর্টিকেলের বডি স্ক্র্যাপ এবং সোশ্যাল মিডিয়া সি.টি.এ ব্লক ফিল্টার করার ফাংশন"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(url, headers=headers, timeout=15)
    soup = BeautifulSoup(response.text, 'html.parser')
    paragraphs = soup.find_all('p')
    cleaned = []
    
    unwanted_phrases = [
        "follow", "read more", "cookies", "subscribe", 
        "social media information", "like our page", 
        "bgn community post", "featured in the linc",
        "the linc!"
    ]
    
    for p in paragraphs:
        txt = p.get_text().strip()
        if len(txt) < 15:
            continue
        if any(k in txt.lower() for k in unwanted_phrases):
            continue
        cleaned.append(txt)
    return "\n\n".join(cleaned)

def hex_to_ass_color(hex_str, opacity_float=1.0):
    hex_str = hex_str.lstrip('#')
    r, g, b = hex_str[0:2], hex_str[2:4], hex_str[4:6]
    alpha_val = int((1.0 - opacity_float) * 255)
    alpha_hex = f"{alpha_val:02X}"
    return f"&H{alpha_hex}{b}{g}{r}"

def fallback_wikimedia_images(keyword, max_results=20):
    """উইকিমিডিয়া কমন্স API থেকে সম্পূর্ণ ফ্রিতে ছবি সার্চ করার ফ্লেক্সিবল ফাংশন"""
    print(f"Trying Wikimedia Commons fallback for: '{keyword}'...")
    try:
        url = "https://commons.wikimedia.org/w/api.php"
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"filetype:bitmap {keyword}",
            "gsrlimit": max_results,
            "prop": "imageinfo",
            "iiprop": "url"
        }
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            data = r.json()
            pages = data.get("query", {}).get("pages", {})
            urls = []
            for page_id, page_info in pages.items():
                image_info = page_info.get("imageinfo", [])
                if image_info:
                    img_url = image_info[0].get("url")
                    if img_url:
                        urls.append(img_url)
            return urls
    except Exception as e:
        print(f"Wikimedia API search failed: {e}")
    return []

def select_thumbnail_and_crop(images_dir, output_thumbnail_path):
    img_files = [f for f in os.listdir(images_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
    sixteen_nine_candidates = []
    
    for f in img_files:
        path = os.path.join(images_dir, f)
        try:
            with Image.open(path) as img:
                w, h = img.size
                ratio = w / h
                if 1.6 <= ratio <= 1.9:  
                    sixteen_nine_candidates.append(path)
        except Exception: pass

    if sixteen_nine_candidates:
        selected = random.choice(sixteen_nine_candidates)
        Image.open(selected).resize((1920, 1080)).save(output_thumbnail_path)
        print(f"Selected native 16:9 thumbnail: {selected}")
    else:
        selected = os.path.join(images_dir, random.choice(img_files))
        Image.open(selected).convert('RGB').resize((1920, 1080)).save(output_thumbnail_path)
        print(f"No native 16:9 found. Cropped random thumbnail: {selected}")

def parse_srt_start_times(srt_path):
    if not os.path.exists(srt_path): return []
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()
    pattern = re.compile(r'(\d{2}):(\d{2}):(\d{2}),(\d{3}) -->')
    matches = pattern.findall(content)
    start_times = []
    for m in matches:
        sec = int(m[0])*3600 + int(m[1])*60 + int(m[2]) + int(m[3])/1000.0
        start_times.append(sec)
    return sorted(list(set(start_times)))

def clear_temp_workspace(workspace_dir, images_dir):
    audio_path = os.path.join(workspace_dir, "audio.mp3")
    srt_path = os.path.join(workspace_dir, "subtitles.srt")
    temp_video = os.path.join(workspace_dir, "temp_video.mp4")
    output_video = os.path.join(workspace_dir, "output_video.mp4")
    thumbnail = os.path.join(workspace_dir, "thumbnail.jpg")
    
    for p in [audio_path, srt_path, temp_video, output_video, thumbnail]:
        if os.path.exists(p):
            try: os.remove(p)
            except Exception: pass
            
    if os.path.exists(images_dir):
        for f in os.listdir(images_dir):
            try: os.remove(os.path.join(images_dir, f))
            except Exception: pass

def upload_to_youtube(video_path, thumbnail_path, title, description):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    print("Authenticating with YouTube API...")
    creds = Credentials(
        token=None,
        refresh_token=os.environ.get('YOUTUBE_REFRESH_TOKEN'),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ.get('YOUTUBE_CLIENT_ID'),
        client_secret=os.environ.get('YOUTUBE_CLIENT_SECRET')
    )
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        'snippet': {
            'title': title[:100],
            'description': description,
            'categoryId': '17'
        },
        'status': {
            'privacyStatus': 'public',
            'selfDeclaredMadeForKids': False
        }
    }

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    video_id = response.get('id')
    print(f"Video uploaded successfully! Video ID: {video_id}")

    if os.path.exists(thumbnail_path):
        youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(thumbnail_path)).execute()
        print("Thumbnail upload completed!")

def main():
    if not os.path.exists("config.json"):
        print("Error: config.json not found!")
        return

    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)

    if not os.path.exists("processed_urls.txt"):
        print("processed_urls.txt not found. Auto-creating a fresh database file...")
        with open("processed_urls.txt", "w", encoding="utf-8") as f:
            f.write("")

    processed_urls = []
    with open("processed_urls.txt", "r", encoding="utf-8") as f:
        processed_urls = [line.strip() for line in f if line.strip()]

    # কনফিগারেশন ভ্যারিয়েবলস 
    rss_list = [url.strip() for url in config["rss_urls"].split(",") if url.strip()]
    exclude_title_kws = [kw.strip().lower() for kw in config["exclude_title_keywords"].split(",") if kw.strip()]
    exclude_body_kws = [kw.strip().lower() for kw in config["exclude_body_keywords"].split(",") if kw.strip()]
    min_words = config.get("min_word_count", 200)
    max_age_hours = float(config.get("max_age_hours", 24.0))

    all_entries = []
    for r_url in rss_list:
        print(f"Parsing Feed: {r_url}")
        try:
            feed = feedparser.parse(r_url)
            for index, entry in enumerate(feed.entries):
                entry.original_index = index 
                all_entries.append(entry)
        except Exception as e:
            print(f"Failed to parse {r_url}: {e}")

    # ক্রনোলজিক্যাল সর্টিং 
    all_entries.sort(key=lambda x: getattr(x, 'published_parsed', None) or getattr(x, 'updated_parsed', None) or (0,), reverse=False)

    candidate_entries = []
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    # ক্যান্ডিডেট ভ্যালিডেশন লুপ 
    for entry in all_entries:
        title = entry.get("title", "")
        link = entry.get("link", "")

        if link in processed_urls: continue

        if exclude_title_kws:
            if any(kw in title.lower() or kw in link.lower() for kw in exclude_title_kws):
                continue

        is_top_feed_item = getattr(entry, 'original_index', 99) < 3
        pub_parsed = getattr(entry, "updated_parsed", None) or getattr(entry, "published_parsed", None)
        if not pub_parsed and not is_top_feed_item: 
            continue
        
        if pub_parsed:
            pub_dt = datetime.datetime(*pub_parsed[:6], tzinfo=datetime.timezone.utc)
            time_diff = now_utc - pub_dt
            time_diff_hours = time_diff.total_seconds() / 3600.0
        else:
            time_diff_hours = 0.0 

        if max_age_hours < 9999.0 and not is_top_feed_item:
            if time_diff_hours > max_age_hours:
                continue

        candidate_entries.append(entry)

    if not candidate_entries:
        print("No new matching articles found. Skipping workflow.")
        return

    print(f"Found {len(candidate_entries)} new articles. Starting Sequential Loop Process...")

    workspace_dir = os.path.join(os.getcwd(), 'workspace')
    images_dir = os.path.join(workspace_dir, 'images')
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(images_dir, exist_ok=True)

    for idx_task, entry in enumerate(candidate_entries):
        title = entry.get("title", "")
        link = entry.get("link", "")

        print(f"\n[{idx_task+1}/{len(candidate_entries)}] Processing: '{title}'...")

        scraped_content = scrape_article(link)
        word_count = len(scraped_content.split())
        
        if word_count < min_words:
            print(f"Skipping: Too short ({word_count} words). Added to processed database.")
            with open("processed_urls.txt", "a", encoding="utf-8") as f: f.write(link + "\n")
            continue

        if exclude_body_kws:
            content_lower = scraped_content.lower()
            if any(kw in content_lower for kw in exclude_body_kws):
                print(f"Skipping: Found forbidden keyword inside body content. Blocked.")
                with open("processed_urls.txt", "a", encoding="utf-8") as f: f.write(link + "\n")
                continue

        # ক্যান্ডিডেট কনফার্মড! ওয়ার্কস্পেস ক্লিন করা হচ্ছে
        clear_temp_workspace(workspace_dir, images_dir)
        print(f"--- FOLDER CLEANED. GENERATING VIDEO FOR: '{title}' ---")

        try:
            # ভয়েস ওভার এবং ক্যাপশন তৈরি 
            audio_path = os.path.join(workspace_dir, "audio.mp3")
            srt_path = os.path.join(workspace_dir, "subtitles.srt")
            asyncio.run(generate_voice_and_subtitles(scraped_content, config["voice"], audio_path, srt_path))

            # ডাইনামিক ইমেজ ডাউনলোডার 
            audio_clip = AudioFileClip(audio_path)
            audio_duration = audio_clip.duration
            audio_clip.close() 

            max_images = 30 if audio_duration > 240.0 else 20
            print(f"Audio Duration: {audio_duration:.2f}s. Dynamic Target: Download {max_images} images.")

            # সার্চ এবং ডাউনলোড 
            words = re.findall(r'\b[A-Z][a-z]{3,}\b', scraped_content)
            keyword = f"{words[0]} {words[1]}" if len(words) >= 2 else "Sports"
            
            urls = []
            try:
                print(f"Searching DDG for {max_images} images: '{keyword}'...")
                results = DDGS().images(keyword, max_results=max_images)
                urls = [r.get('image') for r in results if r.get('image')]
            except Exception as ddg_err:
                print(f"DuckDuckGo search rate-limited or blocked: {ddg_err}")

            # যদি DDG রেট-লিমিট বা ব্লকড হয়, তবে উইকিমিডিয়া এবং আনস্প্ল্যাশ ফলব্যাক দিয়ে ভিডিও চালু রাখব 
            if not urls:
                urls = fallback_wikimedia_images(keyword, max_results=max_images)
            
            if not urls:
                print("No custom images found. Using premium generic sports backdrops as fallback...")
                urls = GENERIC_SPORTS_FALLBACKS * (max_images // len(GENERIC_SPORTS_FALLBACKS) + 1)
                urls = urls[:max_images]

            total_downloaded = 0
            for idx_img, image_url in enumerate(urls):
                try:
                    r = requests.get(image_url, timeout=5)
                    if r.status_code == 200:
                        # এখানে টাইপোটি (idx_img+1) নিখুঁতভাবে নিশ্চিত করা হয়েছে 
                        with open(os.path.join(images_dir, f"img_{idx_img+1:02d}.jpg"), 'wb') as f:
                            f.write(r.content)
                        total_downloaded += 1
                except Exception: pass

            print(f"Collected {total_downloaded} images for rendering.")

            # থাম্বনেইল
            thumbnail_path = os.path.join(workspace_dir, "thumbnail.jpg")
            select_thumbnail_and_crop(images_dir, thumbnail_path)

            # মুভিপাই ভিডিও কম্পাইলেশন 
            audio_clip = AudioFileClip(audio_path)
            audio_duration = audio_clip.duration
            
            img_files = sorted([f for f in os.listdir(images_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
            num_images = len(img_files)

            start_times = parse_srt_start_times(srt_path)
            if not start_times:
                clip_dur = audio_duration / num_images
                start_times = [i*clip_dur for i in range(num_images)]
            else:
                if start_times[0] > 0.1: start_times.insert(0, 0.0)
                else: start_times[0] = 0.0
    
            # অডিও ডিউরেশন বাউন্ডারি 
            start_times.append(audio_duration)

            clips = []
            overlap = 0.5
            num_sentences = len(start_times) - 1

            for i in range(num_sentences):
                t_start = start_times[i]
                t_end = start_times[i+1]
                actual_duration = t_end - t_start
                if actual_duration < 0.2: continue

                img_name = img_files[i % num_images]
                img_path = os.path.join(images_dir, img_name)
                img_pil = Image.open(img_path).convert('RGB')
                w, h = img_pil.size
                ratio = w / h

                if ratio < 1.7:
                    bg_pil = img_pil.resize((1920, 1080)).filter(ImageFilter.GaussianBlur(radius=20))
                    bg_clip = ImageClip(np.array(bg_pil))
                    new_width = int(1080 * ratio)
                    fg_pil = img_pil.resize((new_width, 1080))
                    fg_clip = ImageClip(np.array(fg_pil))

                    if MOVIEPY_V2:
                        bg_clip = bg_clip.with_duration(actual_duration)
                        fg_clip = fg_clip.with_duration(actual_duration).with_position("center")
                        composite_clip = CompositeVideoClip([bg_clip, fg_clip], size=(1920, 1080)).with_duration(actual_duration)
                    else:
                        bg_clip = bg_clip.set_duration(actual_duration)
                        fg_clip = fg_clip.set_duration(actual_duration).set_position("center")
                        composite_clip = CompositeVideoClip([bg_clip, fg_clip], size=(1920, 1080)).set_duration(actual_duration)
                else:
                    ls_pil = img_pil.resize((1920, 1080))
                    composite_clip = ImageClip(np.array(ls_pil))
                    if MOVIEPY_V2: composite_clip = composite_clip.with_duration(actual_duration)
                    else: composite_clip = composite_clip.set_duration(actual_duration)

                if MOVIEPY_V2:
                    if i % 2 == 0: composite_clip = composite_clip.resized(lambda t, d=actual_duration: 1.0 + 0.08 * (t / d))
                    else: composite_clip = composite_clip.resized(lambda t, d=actual_duration: 1.08 - 0.08 * (t / d))
                    composite_clip = composite_clip.with_fps(30).with_position("center").with_start(t_start)
                    if i > 0 and actual_duration > overlap:
                        composite_clip = composite_clip.with_effects([CrossFadeIn(overlap)])
                else:
                    if i % 2 == 0: composite_clip = composite_clip.resize(lambda t, d=actual_duration: 1.0 + 0.08 * (t / d))
                    else: composite_clip = composite_clip.resize(lambda t, d=actual_duration: 1.08 - 0.08 * (t / d))
                    composite_clip = composite_clip.set_fps(30).set_position("center").set_start(t_start)
                    if i > 0 and actual_duration > overlap:
                        composite_clip = composite_clip.crossfadein(overlap)

                clips.append(composite_clip)

            temp_video = os.path.join(workspace_dir, "temp_video.mp4")
            if MOVIEPY_V2:
                final_video = CompositeVideoClip(clips, size=(1920, 1080)).with_duration(audio_duration).with_audio(audio_clip)
            else:
                final_video = CompositeVideoClip(clips, size=(1920, 1080)).set_duration(audio_duration).set_audio(audio_clip)

            num_threads = os.cpu_count() or 4
            final_video.write_videofile(temp_video, fps=30, codec="libx264", audio_codec="aac", threads=num_threads, preset="medium", logger=None)
            audio_clip.close()
            final_video.close()
            for c in clips: c.close()

            # FFmpeg কাস্টম সাবটাইটেল বার্নিং
            f_color = hex_to_ass_color(config["font_color"], 1.0)
            b_color = hex_to_ass_color(config["bg_color"], config["bg_opacity"])
            border_style = config["border_style"]
            font_size = config["font_size"]
            margin_v = config["margin_v"]

            style = f"FontName=Arial,FontSize={font_size},PrimaryColour={f_color},BackColour={b_color},BorderStyle={border_style},Outline=2,Shadow=1,Alignment=2,MarginV={margin_v}"
            
            output_video = os.path.join(workspace_dir, "output_video.mp4")
            cmd = [
                "ffmpeg", "-y", "-i", "temp_video.mp4",
                "-vf", f"subtitles=subtitles.srt:force_style='{style}'",
                "-c:v", "libx264", "-crf", "18", "-c:a", "copy", "output_video.mp4"
            ]
            subprocess.run(cmd, cwd=workspace_dir, check=True)
            
            # ইউটিউব আপলোড 
            desc = f"Latest sports news: {title}\n\nGenerated automatically via AI Cloud System."
            upload_to_youtube(output_video, thumbnail_path, title, desc)

            # ডাটাবেজ আপডেট 
            with open("processed_urls.txt", "a", encoding="utf-8") as f:
                f.write(link + "\n")
            print(f"Database updated for successfully finished video: {title}")

        except Exception as err:
            print(f"Error processing article '{title}': {err}")
            traceback.print_exc()

if __name__ == "__main__":
    main()
