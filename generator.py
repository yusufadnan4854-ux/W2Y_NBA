import os
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
from PIL import Image, ImageFilter, ImageStat
from concurrent.futures import ThreadPoolExecutor
import feedparser  
import edge_tts

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
        unwanted_phrases = ["follow", "read more", "cookies", "subscribe", "social media information", "like our page", "bgn community post", "featured in the linc", "the linc!"]
        
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

def group_paragraphs(paragraphs, min_words=80):
    if not paragraphs:
        return []
    
    groups = []
    temp = []
    
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        
        p_words = p.split()
        if not temp:
            temp.append(p)
        else:
            temp_word_count = len(" ".join(temp).split())
            if temp_word_count < min_words:
                temp.append(p)
            else:
                p_word_count = len(p_words)
                if p_word_count < min_words:
                    temp.append(p)
                else:
                    groups.append("\n\n".join(temp))
                    temp = [p]
    
    if temp:
        temp_word_count = len(" ".join(temp).split())
        if temp_word_count < min_words and groups:
            last_group = groups.pop()
            groups.append(last_group + "\n\n" + "\n\n".join(temp))
        else:
            groups.append("\n\n".join(temp))
            
    return groups

def get_primary_keyword_app_logic(text):
    words = re.findall(r'\b[A-Z][a-z]{3,}\b', text) 
    if len(words) < 2:
        words = re.findall(r'\b[a-zA-Z]{4,}\b', text)
        
    stop_words = {'that', 'this', 'there', 'with', 'from', 'have', 'your', 'which', 'will', 
                  'about', 'like', 'just', 'when', 'what', 'know', 'feel', 'they'}
    filtered = [w for w in words if w.lower() not in stop_words]
    
    if len(filtered) < 2: 
        print("📊 [App Matching Logic] Primary Subject Keyword Extracted: 'NBA Basketball'")
        return "NBA Basketball"
    
    most_common = Counter(filtered).most_common(2)
    keyword = f"{most_common[0][0]} {most_common[1][0]}"
    print(f"📊 [App Matching Logic] Primary Subject Keyword Extracted: '{keyword}'")
    return keyword

def search_vercel_cloud_bridge(keyword, engine="ddg"):
    vercel_endpoint = os.environ.get("VERCEL_BRIDGE_URL")
    if not vercel_endpoint:
        return []
    
    try:
        print(f"🌉 [Vercel Cloud Bridge Active] Fetching High-Res Photos via ({engine}) for: '{keyword}'...")
        url = f"{vercel_endpoint}?q={urllib.parse.quote(keyword)}&engine={engine}&source={engine}"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            images = data.get("images", [])
            print(f"🎉 SUCCESS! Vercel Bridge ({engine}) delivered {len(images)} authentic photos!")
            return images
    except Exception as e:
        print(f"Vercel Bridge ({engine}) Notice: {e}")
        
    return []

def search_bing_direct_photos(keyword, max_results=20):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0.0.0 Safari/537.36'}
        url = f"https://www.bing.com/images/async?q={urllib.parse.quote(keyword)}&first=1&count=25"
        r = requests.get(url, headers=headers, timeout=8)
        if r.status_code == 200:
            urls = re.findall(r'murl&quot;:&quot;(http[^&]+)&quot;', r.text) or re.findall(r'"murl":"(http[^"]+)"', r.text)
            clean_b_links = [u for u in list(dict.fromkeys(urls)) if any(ext in u.lower() for ext in ['.jpg','.jpeg','.png'])]
            print(f"✅ Unblocked Direct Search Engine fetched: {len(clean_b_links)} direct high-res images!")
            return clean_b_links[:max_results]
    except Exception as eb:
        print(f"Direct Search Exception: {eb}")
    return []

def search_wikimedia_images(keyword, max_results=15):
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
    except: pass
    return []

def scrape_images_strictly_web(title, body_text, embedded_photos, num_images_needed=20, append_toggle=False, append_word=""):
    candidates = []
    
    for hero_p in embedded_photos:
        candidates.append(hero_p)
        
    subject = get_primary_keyword_app_logic(body_text)

    if append_toggle and append_word:
        stop_phrases = {
            'los angeles', 'golden state', 'nba basketball', 'summer league', 
            'boston celtics', 'new york', 'miami heat', 'bay area', 'dallas mavericks', 
            'lakers', 'latest update', 'sports news', 'league update', 'news report'
        }
        is_name = False
        
        if subject.lower() not in stop_phrases:
            is_name = bool(re.match(r'^([A-Z][a-zA-Z\'-]+\s+){1,2}[A-Z][a-zA-Z\'-]+$', subject.strip()))
            
        if not is_name:
            subject = f"{subject} {append_word}"
            print(f"🔧 [Modifier Action] Keyword is not a name. Custom suffix appended -> Final Search: '{subject}'")
        else:
            print(f"👤 [Modifier Action] Player name detected! Prefix/Suffix addition skipped -> Final Search: '{subject}'")

    ddg_pics = search_vercel_cloud_bridge(subject, engine="ddg")
    candidates.extend(ddg_pics)
    candidates = list(dict.fromkeys(candidates))

    if len(candidates) >= num_images_needed:
        print(f"🎯 [Smart Stopping] DuckDuckGo delivered {len(candidates)} images which meets the target of {num_images_needed}. Skipping other sources.")
        return candidates

    bing_pics = search_vercel_cloud_bridge(subject, engine="bing")
    candidates.extend(bing_pics)
    candidates = list(dict.fromkeys(candidates))

    if len(candidates) >= num_images_needed:
        return candidates

    wiki_pics = search_vercel_cloud_bridge(subject, engine="wiki")
    candidates.extend(wiki_pics)
    candidates = list(dict.fromkeys(candidates))

    if len(candidates) < 8:
        direct_pics = search_bing_direct_photos(subject, max_results=20)
        candidates.extend(direct_pics)
        candidates = list(dict.fromkeys(candidates))
    if len(candidates) < 8:
        wiki_pics = search_wikimedia_images(subject, max_results=15)
        candidates.extend(wiki_pics)
        candidates = list(dict.fromkeys(candidates))

    return list(dict.fromkeys(candidates))

def filter_and_clean_downloaded_images(images_dir):
    print("🧹 [Dynamic Smart Cleaner] Disabled as per user request. Retaining all downloaded photos.")

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
        except: pass

    try:
        if wide_images:
            Image.open(random.choice(wide_images)).convert("RGB").resize((1920,1080)).save(output_path, quality=95)
        else:
            Image.open(random.choice(all_files)).convert("RGB").resize((1920,1080)).save(output_path, quality=95)
    except: pass

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
    except: pass

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

def get_sentence_timestamps(srt_path):
    if not os.path.exists(srt_path): return []
    with open(srt_path, "r", encoding="utf-8") as srt_reader: content = srt_reader.read()
    regex_clock = re.compile(r'(\d{2}):(\d{2}):(\d{2}),(\d{3}) -->')
    second_values = [int(p[0])*3600 + int(p[1])*60 + int(p[2]) + int(p[3])/1000.0 for p in regex_clock.findall(content)]
    return sorted(list(set(second_values)))

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
    completed_exec = target_job.execute()
    newly_deployed_id = completed_exec.get('id')
    
    print(f"🚀 Mission uploaded successfully! ID: {newly_deployed_id}")

    if os.path.exists(thumb_full_path):
        try:
            google_cloud_instance.thumbnails().set(videoId=newly_deployed_id, media_body=MediaFileUpload(thumb_full_path)).execute()
            print("Associated cover photo added effectively.\n")
        except Exception as e:
            print(f"Thumbnail upload failed: {e}")

def hex_to_ass_color(hex_str, opacity_float=1.0):
    hex_str = hex_str.lstrip('#')
    red, green, blue = hex_str[0:2], hex_str[2:4], hex_str[4:6]
    alpha_hex = int((1.0 - opacity_float) * 255)
    return f"&H{alpha_hex:02X}{blue}{green}{red}"

def get_audio_duration(audio_path):
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", os.path.abspath(audio_path)], capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except: return 0.0

def escape_subtitles_path(path_str):
    escaped = os.path.abspath(path_str).replace("\\", "/")
    if ":" in escaped:
        drive, rest = escaped.split(":", 1)
        escaped = f"{drive}\\:{rest}"
    return escaped

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
        except: pass

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

    print(f"📊 Target Items Found: Processing ALL {len(final_action_items)} matching news articles sequentially for [{time_limit_scale_hrs}h]...")

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
            try:
                parsed_path = urllib.parse.urlparse(lns).path
                path_segments = [p for p in parsed_path.split('/') if p.strip()]
                if path_segments:
                    slug_string = re.sub(r'\.[a-zA-Z0-9]+$', '', path_segments[-1])
                    vid_ttl = slug_string.replace('-', ' ').replace('_', ' ').strip().title()
                
                if not vid_ttl:
                    vid_ttl = "NBA Latest News Update"
            except Exception:
                vid_ttl = "NBA Latest News Update"

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

            rendered_paragraph_videos = []
            raw_paras = text_chunk_collected.split("\n\n")
            raw_paras = [p.strip() for p in raw_paras if p.strip()]

            if calc_tlength < 300.0:
                print("🟢 Video duration < 5 mins. Processing as a single unified timeline...")
                
                global_subject = get_primary_keyword_app_logic(text_chunk_collected)
                
                images_dir = os.path.join(wkspace, "images")
                targ_pcdir = os.path.join(wkspace, 'processed_frames')
                targ_vfrmdir = os.path.join(wkspace, 'rendered_clips')
                os.makedirs(images_dir, exist_ok=True)
                os.makedirs(targ_pcdir, exist_ok=True)
                os.makedirs(targ_vfrmdir, exist_ok=True)

                sentence_timers = get_sentence_timestamps(path_srt)
                if not sentence_timers: 
                    sentence_timers = [0.0, calc_tlength]
                elif sentence_timers[0] > 0.1: 
                    sentence_timers.insert(0, 0.0)
                else: 
                    sentence_timers[0] = 0.0
                if sentence_timers[-1] < calc_tlength - 0.1:
                    sentence_timers.append(calc_tlength)
                total_n_segments = len(sentence_timers) - 1

                num_images_to_download = max(2, min(40, total_n_segments))
                print(f"📥 Length-based download target: downloading {num_images_to_download} images for {total_n_segments} sentences.")

                candidate_image_urls = scrape_images_strictly_web(vid_ttl, text_chunk_collected, embedded_page_photos, num_images_needed=num_images_to_download, append_toggle=append_kwd_feature, append_word=append_suffix)

                successfully_got_downloads = 0
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
                    'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
                }

                for image_link in candidate_image_urls:
                    try:
                        rd = requests.get(image_link, timeout=5, headers=headers)
                        if rd.status_code == 200 and len(rd.content) > 10240: 
                            with open(os.path.join(images_dir, f"imv_dw{successfully_got_downloads:03d}.jpg"), 'wb') as fgxv: 
                                fgxv.write(rd.content)
                            successfully_got_downloads += 1
                    except: pass

                    if successfully_got_downloads >= num_images_to_download:
                        break

                filter_and_clean_downloaded_images(images_dir)
                dflocst = sorted([pzbv for pzbv in os.listdir(images_dir) if pzbv.endswith(('.jpg','.jpeg','.png'))])

                if not dflocst:
                    print("⚠️ No direct photos. Running fallback search with general title keywords...")
                    fallback_urls = scrape_images_strictly_web(vid_ttl, vid_ttl, [], num_images_needed=num_images_to_download, append_toggle=append_kwd_feature, append_word=append_suffix)
                    for image_link in fallback_urls[:5]:
                        try:
                            rd = requests.get(image_link, timeout=5, headers=headers)
                            if rd.status_code == 200 and len(rd.content) > 10240:
                                with open(os.path.join(images_dir, f"imv_dw{successfully_got_downloads:03d}.jpg"), 'wb') as fgxv: 
                                    fgxv.write(rd.content)
                                successfully_got_downloads += 1
                        except: pass
                    filter_and_clean_downloaded_images(images_dir)
                    dflocst = sorted([pzbv for pzbv in os.listdir(images_dir) if pzbv.endswith(('.jpg','.jpeg','.png'))])

                if not dflocst:
                    print("❌ Missing adequate visual web photos. Safely skipping target.")
                    continue

                processed_images = []
                for p_file in dflocst:
                    try:
                        img_path = os.path.join(images_dir, p_file)
                        with Image.open(img_path) as obimgstrm:
                            base_rgb_convert = obimgstrm.convert('RGB')
                            im_w, im_h = base_rgb_convert.size
                            aspect_ratio = im_w / float(im_h)
                            
                            if aspect_ratio >= 1.5:
                                final_path = os.path.join(targ_pcdir, f"pf_land_{p_file}")
                                base_rgb_convert.resize((1920, 1080)).save(final_path, quality=90)
                                processed_images.append({
                                    "type": "landscape",
                                    "path": final_path
                                })
                            else:
                                blurred_bg = base_rgb_convert.resize((1920, 1080)).filter(ImageFilter.GaussianBlur(20))
                                bg_path = os.path.join(targ_pcdir, f"bg_{p_file}")
                                blurred_bg.save(bg_path, quality=90)
                                
                                new_fit_width = int(1080 * aspect_ratio)
                                sharp_fg = base_rgb_convert.resize((new_fit_width, 1080))
                                fg_path = os.path.join(targ_pcdir, f"fg_{p_file}")
                                sharp_fg.save(fg_path, quality=95)
                                
                                processed_images.append({
                                    "type": "portrait",
                                    "bg_path": bg_path,
                                    "fg_path": fg_path
                                })
                    except Exception as e:
                        print(f"Error processing image {p_file}: {e}")

                if not processed_images: 
                    continue

                lines_for_slider_doc = []
                with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as thex:
                    rendered_segment_tasks = []
                    for sg_ix in range(total_n_segments):
                        s_gap = sentence_timers[sg_ix+1] - sentence_timers[sg_ix]
                        if s_gap <= 0.1: continue
                        img_obj = processed_images[sg_ix % len(processed_images)]
                        output_segment_path = os.path.join(targ_vfrmdir, f"seg_{sg_ix:04d}.mp4")
                        rendered_segment_tasks.append(thex.submit(render_segment_by_ffmpeg, sg_ix, s_gap, img_obj, output_segment_path))
                        
                    for task_obj in rendered_segment_tasks: 
                        absolute_clip_path = os.path.abspath(task_obj.result()).replace("\\", "/").replace("'", "'\\''")
                        lines_for_slider_doc.append(f"file '{absolute_clip_path}'")

                tmpsldr_txt_path = os.path.join(wkspace, "temp_slider.txt")
                with open(tmpsldr_txt_path, "w", encoding="utf-8") as fw12z: fw12z.write("\n".join(lines_for_slider_doc))
                
                raw_tmp_output = os.path.join(wkspace, "temp_output.mp4")
                para_final_output = os.path.join(wkspace, "para_0_final.mp4")
                
                path_sfx_mp3 = os.path.join(wkspace, "audio_sfx.mp3")
                mix_sfx_to_audio(path_mp3, sentence_timers, "sound_effects", sfx_volume, path_sfx_mp3)

                subprocess.run(["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-safe", "0", "-f", "concat", "-i", os.path.abspath(tmpsldr_txt_path).replace("\\", "/"), "-i", os.path.abspath(path_sfx_mp3).replace("\\", "/"), "-c:v", "copy", "-c:a", "copy", "-shortest", os.path.abspath(raw_tmp_output).replace("\\", "/")], check=True)

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
                    "-c:a", "copy", os.path.abspath(para_final_output).replace("\\", "/")
                ]
                subprocess.run(subs_cmd, check=True)
                
                rendered_paragraph_videos.append(para_final_output)

            else:
                print("🔵 Video duration >= 5 mins. Grouping every 3 paragraphs as 1 consolidated cluster...")
                
                paragraph_groups = []
                for i in range(0, len(raw_paras), 3):
                    chunk = raw_paras[i:i+3]
                    paragraph_groups.append("\n\n".join(chunk))

                for idx, grp_text in enumerate(paragraph_groups):
                    para_ws = os.path.join(wkspace, f"para_{idx}")
                    images_dir = os.path.join(para_ws, 'images')
                    targ_pcdir = os.path.join(para_ws, 'processed_frames')
                    targ_vfrmdir = os.path.join(para_ws, 'rendered_clips')

                    os.makedirs(para_ws, exist_ok=True)
                    os.makedirs(images_dir, exist_ok=True)
                    os.makedirs(targ_pcdir, exist_ok=True)
                    os.makedirs(targ_vfrmdir, exist_ok=True)

                    print(f"\n🎬 [Processing Cluster {idx+1}/{len(paragraph_groups)}]")
                    
                    path_mp3_grp = os.path.join(para_ws, f"voice_{idx}.mp3")
                    path_srt_grp = os.path.join(para_ws, f"subtitles_{idx}.srt")
                    
                    asyncio.run(generate_voice_and_subtitles(grp_text, user_settings["voice"], path_mp3_grp, path_srt_grp))
                    calc_tlength_grp = get_audio_duration(path_mp3_grp)

                    sentence_timers = get_sentence_timestamps(path_srt_grp)
                    if not sentence_timers: 
                        sentence_timers = [0.0, calc_tlength_grp]
                    elif sentence_timers[0] > 0.1: 
                        sentence_timers.insert(0, 0.0)
                    else: 
                        sentence_timers[0] = 0.0
                    if sentence_timers[-1] < calc_tlength_grp - 0.1:
                        sentence_timers.append(calc_tlength_grp)
                    total_n_segments = len(sentence_timers) - 1

                    num_images_to_download = max(2, min(30, total_n_segments))
                    print(f"📥 Cluster download target: downloading {num_images_to_download} images for {total_n_segments} sentences.")

                    grp_keyword = get_primary_keyword_app_logic(grp_text)
                    
                    candidate_image_urls = scrape_images_strictly_web(vid_ttl, grp_text, embedded_page_photos, num_images_needed=num_images_to_download, append_toggle=append_kwd_feature, append_word=append_suffix)

                    successfully_got_downloads = 0
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
                        'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
                    }

                    for image_link in candidate_image_urls:
                        try:
                            rd = requests.get(image_link, timeout=5, headers=headers)
                            if rd.status_code == 200 and len(rd.content) > 10240: 
                                with open(os.path.join(images_dir, f"imv_dw{successfully_got_downloads:03d}.jpg"), 'wb') as fgxv: 
                                    fgxv.write(rd.content)
                                successfully_got_downloads += 1
                        except: pass

                        if successfully_got_downloads >= num_images_to_download:
                            break

                    filter_and_clean_downloaded_images(images_dir)
                    dflocst = sorted([pzbv for pzbv in os.listdir(images_dir) if pzbv.endswith(('.jpg','.jpeg','.png'))])

                    if not dflocst:
                        print("⚠️ No direct photos. Running fallback search with general title keywords...")
                        fallback_urls = scrape_images_strictly_web(vid_ttl, vid_ttl, [], num_images_needed=num_images_to_download, append_toggle=append_kwd_feature, append_word=append_suffix)
                        for image_link in fallback_urls[:5]:
                            try:
                                rd = requests.get(image_link, timeout=5, headers=headers)
                                if rd.status_code == 200 and len(rd.content) > 10240:
                                    with open(os.path.join(images_dir, f"imv_dw{successfully_got_downloads:03d}.jpg"), 'wb') as fgxv: 
                                        fgxv.write(rd.content)
                                    successfully_got_downloads += 1
                                    
                            except: pass
                        filter_and_clean_downloaded_images(images_dir)
                        dflocst = sorted([pzbv for pzbv in os.listdir(images_dir) if pzbv.endswith(('.jpg','.jpeg','.png'))])

                    if not dflocst:
                        print("❌ Missing adequate visual web photos. Safely skipping paragraph.")
                        continue

                    processed_images = []
                    for p_file in dflocst:
                        try:
                            img_path = os.path.join(images_dir, p_file)
                            with Image.open(img_path) as obimgstrm:
                                base_rgb_convert = obimgstrm.convert('RGB')
                                im_w, im_h = base_rgb_convert.size
                                aspect_ratio = im_w / float(im_h)
                                
                                if aspect_ratio >= 1.5:
                                    final_path = os.path.join(targ_pcdir, f"pf_land_{p_file}")
                                    base_rgb_convert.resize((1920, 1080)).save(final_path, quality=90)
                                    processed_images.append({
                                        "type": "landscape",
                                        "path": final_path
                                    })
                                else:
                                    blurred_bg = base_rgb_convert.resize((1920, 1080)).filter(ImageFilter.GaussianBlur(20))
                                    bg_path = os.path.join(targ_pcdir, f"bg_{p_file}")
                                    blurred_bg.save(bg_path, quality=90)
                                    
                                    new_fit_width = int(1080 * aspect_ratio)
                                    sharp_fg = base_rgb_convert.resize((new_fit_width, 1080))
                                    fg_path = os.path.join(targ_pcdir, f"fg_{p_file}")
                                    sharp_fg.save(fg_path, quality=95)
                                    
                                    processed_images.append({
                                        "type": "portrait",
                                        "bg_path": bg_path,
                                        "fg_path": fg_path
                                    })
                        except Exception as e:
                            print(f"Error processing image {p_file}: {e}")

                    if not processed_images: 
                        continue

                    lines_for_slider_doc = []
                    with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as thex:
                        rendered_segment_tasks = []
                        for sg_ix in range(total_n_segments):
                            s_gap = sentence_timers[sg_ix+1] - sentence_timers[sg_ix]
                            if s_gap <= 0.1: continue
                            img_obj = processed_images[sg_ix % len(processed_images)]
                            output_segment_path = os.path.join(targ_vfrmdir, f"seg_{sg_ix:04d}.mp4")
                            rendered_segment_tasks.append(thex.submit(render_segment_by_ffmpeg, sg_ix, s_gap, img_obj, output_segment_path))
                            
                        for task_obj in rendered_segment_tasks: 
                            absolute_clip_path = os.path.abspath(task_obj.result()).replace("\\", "/").replace("'", "'\\''")
                            lines_for_slider_doc.append(f"file '{absolute_clip_path}'")

                    tmpsldr_txt_path = os.path.join(para_ws, "temp_slider.txt")
                    with open(tmpsldr_txt_path, "w", encoding="utf-8") as fw12z: fw12z.write("\n".join(lines_for_slider_doc))
                    
                    raw_tmp_output = os.path.join(para_ws, "temp_output.mp4")
                    para_final_output = os.path.join(para_ws, f"para_{idx}_final.mp4")
                    
                    path_sfx_mp3 = os.path.join(para_ws, f"voice_{idx}_sfx.mp3")
                    mix_sfx_to_audio(path_mp3_grp, sentence_timers, "sound_effects", sfx_volume, path_sfx_mp3)

                    subprocess.run(["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-safe", "0", "-f", "concat", "-i", os.path.abspath(tmpsldr_txt_path).replace("\\", "/"), "-i", os.path.abspath(path_sfx_mp3).replace("\\", "/"), "-c:v", "copy", "-c:a", "copy", "-shortest", os.path.abspath(raw_tmp_output).replace("\\", "/")], check=True)

                    clx_pri = hex_to_ass_color(user_settings["font_color"], 1.0)
                    clx_bkg = hex_to_ass_color(user_settings["bg_color"], user_settings.get("bg_opacity", 0.6))
                    stylstr_for_subs = f"FontName=Arial,FontSize={user_settings['font_size']},PrimaryColour={clx_pri},OutlineColour={clx_bkg},BackColour={clx_bkg},BorderStyle={user_settings['border_style']},Outline=2,Shadow=1,Alignment=2,MarginV={user_settings['margin_v']}"

                    safe_srt_path = os.path.relpath(path_srt_grp).replace("\\", "/").replace("'", "'\\''")
                    tclmstr_subtitles_filter = f"subtitles='{safe_srt_path}':force_style='{stylstr_for_subs}'"

                    subs_cmd = [
                        "ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", 
                        "-i", os.path.abspath(raw_tmp_output).replace("\\", "/"), 
                        "-vf", tclmstr_subtitles_filter, 
                        "-c:v", "libx264", "-crf", "18", "-preset", "ultrafast", "-tune", "zerolatency",
                        "-c:a", "copy", os.path.abspath(para_final_output).replace("\\", "/")
                    ]
                    subprocess.run(subs_cmd, check=True)
                    
                    rendered_paragraph_videos.append(para_final_output)

            rendered_paragraph_videos = [p for p in rendered_paragraph_videos if os.path.exists(p)]

            if not rendered_paragraph_videos:
                print("⚠️ No paragraph segments successfully generated. Skipping.")
                continue

            print("Designing Dynamic HD Cover Photo...")
            process_dynamic_thumbnail(wkspace, os.path.join(wkspace, "thumbnail.jpg"))

            final_concat_txt = os.path.join(wkspace, "final_concat.txt")
            with open(final_concat_txt, "w", encoding="utf-8") as f:
                for p in rendered_paragraph_videos:
                    safe_p = os.path.abspath(p).replace('\\', '/').replace("'", "'\\''")
                    f.write(f"file '{safe_p}'\n")

            fully_finalized_output = os.path.join(wkspace, "output_video.mp4")
            print("🔗 Merging all processed segment clips into finalized master timeline...")
            subprocess.run(["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-safe", "0", "-f", "concat", "-i", os.path.abspath(final_concat_txt).replace("\\", "/"), "-c", "copy", os.path.abspath(fully_finalized_output).replace("\\", "/")], check=True)

            safe_upload_to_youtube(fully_finalized_output, os.path.join(wkspace, "thumbnail.jpg"), vid_ttl, f"Complete Highlights Recap: {vid_ttl}")
            
            with open("processed_urls.txt", "a", encoding="utf-8") as fwx_docv: fwx_docv.write(lns+"\n")
            print("================ 🎯 Complete Workflow Operations executed successfully seamlessly! 💯 ================\n")

        except Exception as errp: traceback.print_exc()

if __name__ == "__main__":
    process_primary_automation_loop()