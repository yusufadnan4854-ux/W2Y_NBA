import os
import sys
import re
import json
import random
import datetime  
import asyncio
import requests
import traceback
import subprocess  
import urllib.parse
import shutil
from bs4 import BeautifulSoup
from collections import Counter
from PIL import Image, ImageFilter
from concurrent.futures import ThreadPoolExecutor
import feedparser  
import edge_tts

# ইউটিউব কোটা শেষ হলে লুপ ব্রেক করার জন্য কাস্টম এক্সেপশন
class YoutubeQuotaExceededException(Exception):
    pass

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
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36'}
    try:
        response = requests.get(url, headers=headers, timeout=12)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        cleaned_paragraphs = []
        unwanted_phrases = [
            "follow", "read more", "cookies", "subscribe", "social media information", 
            "like our page", "bgn community post", "featured in the linc", "the linc!",
            "facebook, instagram", "tiktok, x", "whatsapp, linkedin", "sign up here", 
            "download here", "newsletters:", "home delivery:"
        ]
        
        for p in soup.find_all('p'):
            text = p.get_text().strip()
            if len(text) < 15 or any(k in text.lower() for k in unwanted_phrases): 
                continue
            cleaned_paragraphs.append(text)
            
        article_text = "\n\n".join(cleaned_paragraphs)
        
        embedded_article_photos = []
        for meta in soup.find_all('meta'):
            if meta.get('property') in ['og:image', 'twitter:image']:
                c = meta.get('content')
                if c and c.startswith('http') and not any(j in c.lower() for j in ['logo', 'icon', 'default', 'avatar', 'ad']): 
                    embedded_article_photos.append(c)
                    
        return article_text, list(dict.fromkeys(embedded_article_photos))
    except:
        return "", []

# --- GROQ LLM: ১. আর্টিকেলের প্রধান বিষয় (Main Subject) বের করার ফাংশন ---
def get_primary_subject_llm(text):
    groq_api_key = os.environ.get("GROQ_API_KEY")
    if groq_api_key and text and text.strip():
        try:
            print("🤖 [Groq LLM Active] Extracting Main Subject Entity...")
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {groq_api_key}",
                "Content-Type": "application/json"
            }
            prompt = f"""You are a sports video editor. Analyze the article snippet below and return ONLY the SINGLE MAIN SUBJECT (Main Player Name, Main Team, or Primary Entity).

Rules:
1. Output ONLY 1 to 3 words (e.g. "LeBron James", "Boston Celtics", "Victor Wembanyama").
2. NO quotes, NO explanations, NO extra punctuation.
3. Must be ideal for image search engines.

Article Snippet:
{text[:1500]}
"""
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 15
            }
            r = requests.post(url, headers=headers, json=payload, timeout=8)
            if r.status_code == 200:
                subject = r.json()['choices'][0]['message']['content'].strip()
                subject = re.sub(r'["\'.]', '', subject).strip().title()
                if subject:
                    print(f"🎯 [Groq Main Subject Identified]: '{subject}'")
                    return subject
        except Exception as e:
            print(f"⚠️ Groq Main Subject Extraction exception: {e}")

    # Fallback logic (Regex)
    raw_names = re.findall(r"\b[A-Z][a-zA-Z\'-]+\s+[A-Z][a-zA-Z\'-]+\b", text)
    if raw_names:
        return Counter(raw_names).most_common(1)[0][0]
    return "Sports Highlights"

# --- GROQ LLM: ২. বাক্য অনুযায়ী Anchor + Context ইমেজ সার্চ কোয়েরি তৈরি ---
def get_sentence_queries_llm(sentences_list, main_subject):
    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key or not sentences_list:
        return [main_subject] * len(sentences_list)

    formatted_sentences = "\n".join([f"{idx+1}. {s}" for idx, s in enumerate(sentences_list)])

    prompt = f"""You are an AI video editor matching images to video narration sentences.
Main Subject / Anchor: "{main_subject}"

Task: For each numbered sentence below, generate a 2 to 4-word Google Image search query.

CRITICAL RULES:
1. EVERY query MUST contain the Main Subject "{main_subject}" or the Team Name to anchor context.
2. Format: [Main Subject] + [Specific Sentence Action/Context].
3. NO generic metaphors (e.g., do NOT use "thunderbolt", "storm", "magic", "fire").
4. Output MUST be a strict JSON object containing a key "queries" with an array of strings matching sentence order.

Sentences:
{formatted_sentences}

Example Output:
{{
  "queries": [
    "{main_subject} game action",
    "{main_subject} dunk basket",
    "{main_subject} press conference"
  ]
}}
"""
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {groq_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "response_format": {"type": "json_object"}
        }
        r = requests.post(url, headers=headers, json=payload, timeout=12)
        if r.status_code == 200:
            data = json.loads(r.json()['choices'][0]['message']['content'])
            queries = data.get("queries", [])
            if isinstance(queries, list) and len(queries) == len(sentences_list):
                cleaned = [re.sub(r'["\'.]', '', str(q)).strip() for q in queries]
                print(f"⚡ [Groq Sentence Queries Generated]: {len(cleaned)} queries for {len(sentences_list)} sentences.")
                return cleaned
    except Exception as e:
        print(f"⚠️ Groq Sentence Queries generation failed: {e}")

    return [main_subject] * len(sentences_list)

def search_vercel_cloud_bridge(keyword, engine="ddg"):
    vercel_endpoint = os.environ.get("VERCEL_BRIDGE_URL")
    if not vercel_endpoint:
        return []
    
    try:
        url = f"{vercel_endpoint}?q={urllib.parse.quote(keyword)}&engine={engine}&source={engine}"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json().get("images", [])
    except Exception:
        pass
        
    return []

def search_bing_direct_photos(keyword, max_results=20):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0.0.0 Safari/537.36'}
        url = f"https://www.bing.com/images/async?q={urllib.parse.quote(keyword)}&first=1&count=25"
        r = requests.get(url, headers=headers, timeout=8)
        if r.status_code == 200:
            urls = re.findall(r'murl&quot;:&quot;(http[^&]+)&quot;', r.text) or re.findall(r'"murl":"(http[^"]+)"', r.text)
            clean_b_links = [u for u in list(dict.fromkeys(urls)) if any(ext in u.lower() for ext in ['.jpg','.jpeg','.png'])]
            return clean_b_links[:max_results]
    except Exception:
        pass
    return []

def search_wikimedia_images(keyword, max_results=15):
    try:
        url = "https://commons.wikimedia.org/w/api.php"
        params = {
            "action": "query", "format": "json",
            "generator": "search", "gsrsearch": f"filetype:bitmap {keyword}",
            "gsrlimit": max_results, "prop": "imageinfo", "iiprop": "url"
        }
        r = requests.get(url, params=params, timeout=8)
        if r.status_code == 200:
            pages = r.json().get("query", {}).get("pages", {})
            urls = []
            for p in pages.values():
                imageinfo = p.get("imageinfo")
                if imageinfo and len(imageinfo) > 0:
                    img_url = imageinfo[0].get("url")
                    if img_url and any(ext in img_url.lower() for ext in ['.jpg','.png','.jpeg']):
                        urls.append(img_url)
            return urls
    except Exception:
        pass
    return []

def fetch_images_for_query(query, embedded_photos=[], num_needed=3, append_toggle=False, append_word=""):
    candidates = []
    for hero_p in embedded_photos:
        candidates.append(hero_p)
        
    search_term = query
    if append_toggle and append_word:
        if not re.match(r'^([A-Z][a-zA-Z\'-]+\s+){1,2}[A-Z][a-zA-Z\'-]+$', query.strip()):
            search_term = f"{query} {append_word}".strip()

    ddg_pics = search_vercel_cloud_bridge(search_term, engine="ddg")
    candidates.extend(ddg_pics)
    candidates = list(dict.fromkeys(candidates))

    if len(candidates) < num_needed:
        bing_pics = search_vercel_cloud_bridge(search_term, engine="bing")
        candidates.extend(bing_pics)
        candidates = list(dict.fromkeys(candidates))

    if len(candidates) < num_needed:
        direct_pics = search_bing_direct_photos(search_term, max_results=15)
        candidates.extend(direct_pics)
        candidates = list(dict.fromkeys(candidates))

    return candidates

def process_dynamic_thumbnail(wkspace, output_path):
    all_files = []
    for root, dirs, files in os.walk(wkspace):
        for f in files:
            if f.lower().endswith(('.jpg', '.jpeg', '.png')) and "images" in root:
                all_files.append(os.path.join(root, f))
                
    if not all_files: return
    
    wide_images = []
    for f in all_files:
        try:
            with Image.open(f) as iobj:
                w, h = iobj.size
                if 1.6 <= w/h <= 1.9: wide_images.append(f)
        except Exception:
            pass

    try:
        if wide_images:
            Image.open(random.choice(wide_images)).convert("RGB").resize((1920,1080)).save(output_path, quality=95)
        else:
            Image.open(random.choice(all_files)).convert("RGB").resize((1920,1080)).save(output_path, quality=95)
    except Exception:
        pass

def clear_temporary_workspace(ws_dir):
    try:
        os.makedirs(ws_dir, exist_ok=True)
        for fname in ["audio.mp3", "subtitles.srt", "temp_slider.txt", "temp_output.mp4", "output_video.mp4", "thumbnail.jpg", "final_concat.txt"]:
            fpath = os.path.join(ws_dir, fname)
            if os.path.exists(fpath): os.remove(fpath)

        for name in os.listdir(ws_dir):
            path = os.path.join(ws_dir, name)
            if os.path.isdir(path):
                shutil.rmtree(path)
    except Exception:
        pass

def render_segment_by_ffmpeg(clip_index, segment_duration, img_obj, output_segment_path):
    frame_count = max(int(segment_duration * 30), 10)
    
    if img_obj["type"] == "landscape":
        step_str = f"{0.15 / frame_count:.6f}"
        if clip_index % 2 == 0:
            lens_filter = f"scale=3840x2160,zoompan=z='min(1.15, zoom+{step_str})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frame_count}:s=3840x2160:fps=30,scale=1920x1080"
        else:
            lens_filter = f"scale=3840x2160,zoompan=z='if(lte(zoom,1.0),1.15,max(1.001,zoom-{step_str}))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frame_count}:s=3840x2160:fps=30,scale=1920x1080"
        
        cmd_arguments = [
            "ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", 
            "-loop", "1", "-framerate", "30", "-i", img_obj["path"], 
            "-vf", lens_filter, "-t", f"{segment_duration:.2f}", 
            "-c:v", "libx264", "-preset", "ultrafast", 
            "-tune", "zerolatency", "-pix_fmt", "yuv420p", output_segment_path
        ]
        subprocess.run(cmd_arguments, check=True)
    else:
        bg_p = img_obj["bg_path"]
        fg_p = img_obj["fg_path"]
        
        if clip_index % 2 == 0:
            slide_filter = f"[0:v][1:v]overlay=x='(W-w)/2 - 60 + 120*(t/{segment_duration:.2f})':y=0[out]"
        else:
            slide_filter = f"[0:v][1:v]overlay=x='(W-w)/2 + 60 - 120*(t/{segment_duration:.2f})':y=0[out]"
            
        cmd_arguments = [
            "ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", 
            "-loop", "1", "-i", bg_p, 
            "-loop", "1", "-i", fg_p, 
            "-filter_complex", slide_filter, "-map", "[out]", 
            "-t", f"{segment_duration:.2f}", "-r", "30", "-c:v", "libx264", "-preset", "ultrafast", 
            "-tune", "zerolatency", "-pix_fmt", "yuv420p", output_segment_path
        ]
        subprocess.run(cmd_arguments, check=True)
        
    return output_segment_path

def mix_sfx_to_audio(audio_path, timestamps, sfx_folder, sfx_volume, output_audio_path):
    if not os.path.exists(sfx_folder):
        shutil.copyfile(audio_path, output_audio_path)
        return
        
    sfx_files = [os.path.join(sfx_folder, f) for f in os.listdir(sfx_folder) if f.lower().endswith(('.mp3', '.wav'))]
    if not sfx_files or len(timestamps) <= 1:
        shutil.copyfile(audio_path, output_audio_path)
        return
        
    cmd = ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", audio_path]
    filter_inputs = []
    
    valid_ts = [t for t in timestamps[1:-1] if t > 0.1]
    
    for idx, ts in enumerate(valid_ts):
        sfx = random.choice(sfx_files)
        cmd.extend(["-i", sfx])
        ms = int(ts * 1000)
        filter_inputs.append(f"[{idx+1}:a]volume={sfx_volume:.2f},adelay=delays={ms}:all=1[sfx{idx}]")
        
    if filter_inputs:
        mix_labels = "".join(f"[sfx{idx}]" for idx in range(len(valid_ts)))
        filter_complex = ";".join(filter_inputs) + f";[0:a]{mix_labels}amix=inputs={len(valid_ts)+1}:normalize=0[out]"
        cmd.extend(["-filter_complex", filter_complex, "-map", "[out]"])
    else:
        cmd.extend(["-c:a", "copy"])
        
    cmd.append(output_audio_path)
    subprocess.run(cmd, check=True)

def parse_srt_data(srt_path):
    if not os.path.exists(srt_path): return [], []
    with open(srt_path, "r", encoding="utf-8") as f: content = f.read()
    blocks = re.split(r'\n\n+', content.strip())
    
    time_pairs = []
    sentences = []
    regex_clock = re.compile(r'(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})')
    
    for b in blocks:
        lines = [l.strip() for l in b.split('\n') if l.strip()]
        if len(lines) >= 3:
            m = regex_clock.search(lines[1])
            if m:
                st = int(m.group(1))*3600 + int(m.group(2))*60 + int(m.group(3)) + int(m.group(4))/1000.0
                et = int(m.group(5))*3600 + int(m.group(6))*60 + int(m.group(7)) + int(m.group(8))/1000.0
                stxt = " ".join(lines[2:])
                time_pairs.append((st, et))
                sentences.append(stxt)
                
    return time_pairs, sentences

def safe_upload_to_youtube(video_full_path, thumb_full_path, title, video_description):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    print("\nProcessing backend google security auth directly with secrets variables provided in workflow ...")
    authorized_keys = Credentials(
        token=None, refresh_token=os.environ.get('YOUTUBE_REFRESH_TOKEN'), 
        token_uri="https://oauth2.googleapis.com/token", 
        client_id=os.environ.get('YOUTUBE_CLIENT_ID'), 
        client_secret=os.environ.get('YOUTUBE_CLIENT_SECRET')
    )
    google_cloud_instance = build("youtube", "v3", credentials=authorized_keys)

    body = {
        'snippet': {'title': title[:98], 'description': video_description, 'categoryId': '17'}, 
        'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}
    }
    target_job = google_cloud_instance.videos().insert(
        part="snippet,status", 
        body=body, 
        media_body=MediaFileUpload(video_full_path, resumable=True, mimetype="video/mp4")
    )
    try:
        completed_exec = target_job.execute()
        newly_deployed_id = completed_exec.get('id')
        print(f"🚀 Mission uploaded successfully! ID: {newly_deployed_id}")

        if os.path.exists(thumb_full_path):
            try:
                google_cloud_instance.thumbnails().set(videoId=newly_deployed_id, media_body=MediaFileUpload(thumb_full_path)).execute()
                print("Associated cover photo added effectively.\n")
            except Exception as e:
                print(f"Thumbnail upload failed: {e}")
    except Exception as e:
        err_msg = str(e)
        if "quota" in err_msg.lower() or "limit" in err_msg.lower() or "429" in err_msg:
            print("\n🛑 [Quota Exhausted] YouTube API Daily Upload Quota Limit Exceeded!")
            raise YoutubeQuotaExceededException("YouTube API upload quota exceeded.") from e
        else:
            print(f"❌ YouTube upload failed with unexpected error: {e}")
            raise e

def hex_to_ass_color(hex_str, opacity_float=1.0):
    hex_str = hex_str.lstrip('#')
    red, green, blue = hex_str[0:2], hex_str[2:4], hex_str[4:6]
    alpha_hex = int((1.0 - opacity_float) * 255)
    return f"&H{alpha_hex:02X}{blue}{green}{red}"

def get_audio_duration(audio_path):
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", os.path.abspath(audio_path)], capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except Exception:
        return 0.0

def process_primary_automation_loop():
    if not os.path.exists("config.json"): return
    with open("config.json", "r", encoding="utf-8") as cf: user_settings = json.load(cf)

    if not os.path.exists("processed_urls.txt"):
        with open("processed_urls.txt", "w", encoding="utf-8") as cx: cx.write("")
    with open("processed_urls.txt", "r", encoding="utf-8") as pc_rd: done_records = [l.strip() for l in pc_rd if l.strip()]

    collected_feeds, dt_utcnow = [], datetime.datetime.now(datetime.timezone.utc)
    target_urls_parsed = [x.strip() for x in user_settings["rss_urls"].split(",") if x.strip()]
    
    for rss_path in target_urls_parsed:
        try:
            p_feed = feedparser.parse(rss_path)
            for list_id, p_obj in enumerate(p_feed.entries): 
                p_obj.rss_hierarchy = list_id
                collected_feeds.append(p_obj)
        except Exception:
            pass

    collected_feeds.sort(key=lambda sxy: getattr(sxy, 'published_parsed', None) or getattr(sxy, 'updated_parsed', None) or (0,), reverse=False)

    filter_excluded_title = [xtr.strip().lower() for xtr in user_settings["exclude_title_keywords"].split(",") if xtr.strip()]
    time_limit_scale_hrs = float(user_settings.get("max_age_hours", 24.0))

    final_action_items = []
    for fitem in collected_feeds:
        a_title, a_link = fitem.get("title", ""), fitem.get("link", "")
        if a_link in done_records: 
            continue
            
        skip_article = False
        if filter_excluded_title:
            for spam_word in filter_excluded_title:
                if spam_word in a_title.lower() or spam_word in a_link.lower():
                    skip_article = True
                    break
        if skip_article: continue

        draft_priority = getattr(fitem, 'rss_hierarchy', 99) < 3
        actual_calendar_data = getattr(fitem, "published_parsed", getattr(fitem, "updated_parsed", None))
        
        if not actual_calendar_data and not draft_priority: continue
        diff_tracker = (dt_utcnow - datetime.datetime(*actual_calendar_data[:6], tzinfo=datetime.timezone.utc)).total_seconds() / 3600.0 if actual_calendar_data else 0.0
        if time_limit_scale_hrs < 9999.0 and not draft_priority and diff_tracker > time_limit_scale_hrs: 
            continue
            
        final_action_items.append(fitem)

    if not final_action_items: 
        print("Completed database scraping securely. Scheduled task waiting.")
        return

    print(f"📊 Target Items Found: Processing ALL {len(final_action_items)} matching news articles sequentially...")

    wkspace = os.path.abspath(os.path.join(os.getcwd(), 'workspace'))
    blocked_inside_words = [bk.strip().lower() for bk in user_settings["exclude_body_keywords"].split(",") if bk.strip()]
    require_wc = user_settings.get("min_word_count", 150)
    sfx_volume = user_settings.get("sfx_volume", 0.3)
    
    append_kwd_feature = user_settings.get("append_keyword_feature", False)
    append_suffix = user_settings.get("append_word_suffix", "")

    for track_loop_counter, finalizer_target in enumerate(final_action_items):
        vid_ttl, lns = finalizer_target.get("title", ""), finalizer_target.get("link", "")
        vid_ttl = str(vid_ttl).strip()
        if not vid_ttl or vid_ttl.lower() == "unknown":
            vid_ttl = "Latest Update"

        print(f"\n=========================================================================")
        print(f"[{track_loop_counter+1}/{len(final_action_items)}] Processing Target Article: >> {vid_ttl}")
        print(f"=========================================================================")

        text_chunk_collected, embedded_page_photos = scrape_article(lns)
        content_word_size = len(text_chunk_collected.split())
        
        if content_word_size < require_wc:
            with open("processed_urls.txt", "a") as fwpt: fwpt.write(lns+"\n"); continue
            
        body_trap = False
        if blocked_inside_words:
            for sw_in_b in blocked_inside_words:
                if sw_in_b in text_chunk_collected.lower():
                    body_trap = True; break
        if body_trap:
            with open("processed_urls.txt", "a") as bwf: bwf.write(lns+"\n"); continue

        clear_temporary_workspace(wkspace)

        try:
            path_mp3 = os.path.join(wkspace, "audio.mp3")
            path_srt = os.path.join(wkspace, "subtitles.srt")
            
            print("Encoding Edge-TTS Audio and generating SRT timing anchors...")
            asyncio.run(generate_voice_and_subtitles(text_chunk_collected, user_settings["voice"], path_mp3, path_srt))
            calc_tlength = get_audio_duration(path_mp3)
            print(f"⏱️ Total generated audio duration: {calc_tlength:.2f} seconds.")

            # SRT ফাইল থেকে সময় ও বাক্য এক্সট্র্যাক্ট করা
            time_pairs, sentences_list = parse_srt_data(path_srt)
            if not sentences_list:
                print("❌ Subtitles/Sentences generation failed. Skipping.")
                continue

            # ১. Groq LLM দিয়ে মূল সাবজেক্ট বের করা
            main_subject = get_primary_subject_llm(text_chunk_collected)

            # ২. Groq LLM দিয়ে প্রতি বাক্যের জন্য Anchor + Context ইমেজ সার্চ কোয়েরি তৈরি করা
            sentence_queries = get_sentence_queries_llm(sentences_list, main_subject)

            images_dir = os.path.join(wkspace, "images")
            targ_pcdir = os.path.join(wkspace, 'processed_frames')
            targ_vfrmdir = os.path.join(wkspace, 'rendered_clips')
            os.makedirs(images_dir, exist_ok=True)
            os.makedirs(targ_pcdir, exist_ok=True)
            os.makedirs(targ_vfrmdir, exist_ok=True)

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0.0.0 Safari/537.36',
                'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
            }

            # ৩. প্রতি বাক্যের জন্য আলাদা ছবি ডাউনলোড করা
            downloaded_segment_images = []
            for s_idx, query in enumerate(sentence_queries):
                candidate_urls = fetch_images_for_query(query, embedded_page_photos if s_idx == 0 else [], num_needed=2, append_toggle=append_kwd_feature, append_word=append_suffix)
                
                saved_img_path = None
                for c_url in candidate_urls:
                    try:
                        rd = requests.get(c_url, timeout=5, headers=headers)
                        if rd.status_code == 200 and len(rd.content) > 10240:
                            img_file = os.path.join(images_dir, f"seg_{s_idx:03d}.jpg")
                            with open(img_file, 'wb') as fgxv:
                                fgxv.write(rd.content)
                            saved_img_path = img_file
                            break
                    except Exception:
                        pass

                # যদি সুনির্দিষ্ট কোয়েরির ছবি না পাওয়া যায়, তবে Main Subject দিয়ে ব্যাকআপ ডাউনলোড
                if not saved_img_path:
                    backup_urls = fetch_images_for_query(main_subject, [], num_needed=2, append_toggle=append_kwd_feature, append_word=append_suffix)
                    for b_url in backup_urls:
                        try:
                            rd = requests.get(b_url, timeout=5, headers=headers)
                            if rd.status_code == 200 and len(rd.content) > 10240:
                                img_file = os.path.join(images_dir, f"seg_{s_idx:03d}.jpg")
                                with open(img_file, 'wb') as fgxv:
                                    fgxv.write(rd.content)
                                saved_img_path = img_file
                                break
                        except Exception:
                            pass

                downloaded_segment_images.append(saved_img_path)

            # ৪. ডাউনলোড করা ছবি প্রসেস করা (Landscape vs Portrait Blur Background)
            processed_images_list = []
            for s_idx, img_p in enumerate(downloaded_segment_images):
                if not img_p or not os.path.exists(img_p):
                    # ফলব্যাক: আগের প্রসেসড ছবি ব্যবহার করা
                    if processed_images_list:
                        processed_images_list.append(processed_images_list[-1])
                    continue

                try:
                    with Image.open(img_p) as obimgstrm:
                        base_rgb_convert = obimgstrm.convert('RGB')
                        im_w, im_h = base_rgb_convert.size
                        aspect_ratio = im_w / float(im_h)
                        
                        if aspect_ratio >= 1.5:
                            final_path = os.path.join(targ_pcdir, f"pf_land_{s_idx:03d}.jpg")
                            base_rgb_convert.resize((1920, 1080)).save(final_path, quality=90)
                            processed_images_list.append({"type": "landscape", "path": final_path})
                        else:
                            blurred_bg = base_rgb_convert.resize((1920, 1080)).filter(ImageFilter.GaussianBlur(20))
                            bg_path = os.path.join(targ_pcdir, f"bg_{s_idx:03d}.jpg")
                            blurred_bg.save(bg_path, quality=90)
                            
                            new_fit_width = int(1080 * aspect_ratio)
                            sharp_fg = base_rgb_convert.resize((new_fit_width, 1080))
                            fg_path = os.path.join(targ_pcdir, f"fg_{s_idx:03d}.jpg")
                            sharp_fg.save(fg_path, quality=95)
                            
                            processed_images_list.append({"type": "portrait", "bg_path": bg_path, "fg_path": fg_path})
                except Exception as e:
                    print(f"Error processing frame {img_p}: {e}")

            if not processed_images_list:
                print("❌ Missing valid images. Safely skipping target.")
                continue

            # ৫. প্রতিটি বাক্য এবং তার ছবির জন্য ক্লিপ রেন্ডার করা
            lines_for_slider_doc = []
            with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as thex:
                rendered_segment_tasks = []
                for sg_ix, (st, et) in enumerate(time_pairs):
                    s_gap = et - st
                    if s_gap <= 0.1: continue
                    img_obj = processed_images_list[sg_ix % len(processed_images_list)]
                    output_segment_path = os.path.join(targ_vfrmdir, f"seg_{sg_ix:04d}.mp4")
                    rendered_segment_tasks.append(thex.submit(render_segment_by_ffmpeg, sg_ix, s_gap, img_obj, output_segment_path))
                    
                for task_obj in rendered_segment_tasks: 
                    absolute_clip_path = os.path.abspath(task_obj.result()).replace("\\", "/").replace("'", "'\\''")
                    lines_for_slider_doc.append(f"file '{absolute_clip_path}'")

            tmpsldr_txt_path = os.path.join(wkspace, "temp_slider.txt")
            with open(tmpsldr_txt_path, "w", encoding="utf-8") as fw12z: fw12z.write("\n".join(lines_for_slider_doc))
            
            raw_tmp_output = os.path.join(wkspace, "temp_output.mp4")
            master_final_output = os.path.join(wkspace, "output_video.mp4")
            
            # ব্যাকগ্রাউন্ড সাউন্ড ইফেক্ট যুক্ত করা
            path_sfx_mp3 = os.path.join(wkspace, "audio_sfx.mp3")
            mix_sfx_to_audio(path_mp3, [tp[0] for tp in time_pairs], "sound_effects", sfx_volume, path_sfx_mp3)

            # ক্লিপ ও অডিও মার্জ করা
            subprocess.run(["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-safe", "0", "-f", "concat", "-i", os.path.abspath(tmpsldr_txt_path).replace("\\", "/"), "-i", os.path.abspath(path_sfx_mp3).replace("\\", "/"), "-c:v", "copy", "-c:a", "copy", "-shortest", os.path.abspath(raw_tmp_output).replace("\\", "/")], check=True)

            # সাবটাইটেল ডিজাইন বার্ন করা (Subtitle Burn)
            clx_pri = hex_to_ass_color(user_settings["font_color"], 1.0)
            clx_bkg = hex_to_ass_color(user_settings["bg_color"], user_settings.get("bg_opacity", 0.6))
            stylstr_for_subs = f"FontName=Arial,FontSize={user_settings['font_size']},PrimaryColour={clx_pri},OutlineColour={clx_bkg},BackColour={clx_bkg},BorderStyle={user_settings['border_style']},Outline=2,Shadow=1,Alignment=2,MarginV={user_settings['margin_v']}"

            safe_srt_path = os.path.relpath(path_srt).replace("\\", "/").replace("'", "'\\''")
            tclmstr_subtitles_filter = f"subtitles='{safe_srt_path}':force_style='{stylstr_for_subs}'"

            subs_cmd = [
                "ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", 
                "-i", os.path.abspath(raw_tmp_output).replace("\\", "/"), 
                "-vf", tclmstr_subtitles_filter, 
                "-c:v", "libx264", "-crf", "18", "-preset", "ultrafast", "-tune", "zerolatency",
                "-c:a", "copy", os.path.abspath(master_final_output).replace("\\", "/")
            ]
            subprocess.run(subs_cmd, check=True)

            # থাম্বনেইল তৈরি
            process_dynamic_thumbnail(wkspace, os.path.join(wkspace, "thumbnail.jpg"))

            # ভিডিও ইউটিউবে আপলোড করা
            safe_upload_to_youtube(master_final_output, os.path.join(wkspace, "thumbnail.jpg"), vid_ttl, f"Complete Highlights Recap: {vid_ttl}")
            
            with open("processed_urls.txt", "a", encoding="utf-8") as fwx_docv: fwx_docv.write(lns+"\n")
            print("================ 🎯 Complete Workflow Operations executed successfully seamlessly! 💯 ================\n")

        except YoutubeQuotaExceededException:
            print("\n🛑 stopping loop: YouTube Daily Upload Quota is fully exhausted.")
            break
        except Exception as errp: 
            traceback.print_exc()

if __name__ == "__main__":
    process_primary_automation_loop()