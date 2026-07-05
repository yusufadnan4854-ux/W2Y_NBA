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
from bs4 import BeautifulSoup
from collections import Counter
from PIL import Image, ImageFilter, ImageStat
from concurrent.futures import ThreadPoolExecutor
import feedparser  
import edge_tts

# ১০০% ভেরিফায়েড শুধুই বাস্কেটবল স্টেডিয়াম কোট ও স্পোর্টস প্রোপার্টিজ (ফুটবলের যেকোনো ট্রেস মুক্ত!)
VERIFIED_BASKETBALL_STOCKS = [
    "https://images.unsplash.com/photo-1546519638-68e109498ffc?w=1920&q=80",  # Hoop
    "https://images.unsplash.com/photo-1519766304817-4f37bda74a27?w=1920&q=80",  # Indoor Court
    "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?w=1920&q=80",  # Stadium
    "https://images.unsplash.com/photo-1518063319789-7217e6706b04?w=1920&q=80",  # Net Ball
    "https://images.unsplash.com/photo-1579952363873-27f3bade9f55?w=1920&q=80",  # NBA Jersey
    "https://images.unsplash.com/photo-1608245449230-4ac19066d210?w=1920&q=80",  # NBA Court
    "https://images.unsplash.com/photo-1519861531473-9200262188bf?w=1920&q=80"   # Arena Match
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
        
        # সংবাদের পাতার নিজস্ব জেনুইন অরিজিনাল কভার ফোটোজ নেওয়া
        embedded_article_photos = []
        for meta in soup.find_all('meta'):
            if meta.get('property') in ['og:image', 'twitter:image']:
                c = meta.get('content')
                if c and c.startswith('http') and not any(j in c.lower() for j in ['logo', 'icon', 'default', 'avatar', 'ad']): 
                    embedded_article_photos.append(c)
                    
        return article_text, list(dict.fromkeys(embedded_article_photos))
    except:
        return "", []

def get_primary_keyword_app_logic(text):
    words = re.findall(r'\b[A-Z][a-z]{3,}\b', text) 
    if len(words) < 2:
        words = re.findall(r'\b[a-zA-Z]{4,}\b', text)
        
    stop_words = {'that', 'this', 'there', 'with', 'from', 'have', 'your', 'which', 'will', 
                  'about', 'like', 'just', 'when', 'what', 'know', 'feel', 'they', 'team', 'game', 'news', 'first', 'report', 'league'}
    filtered = [w for w in words if w.lower() not in stop_words]
    
    if len(filtered) < 2: 
        return "NBA Basketball match"
        
    most_common = Counter(filtered).most_common(2)
    keyword = f"{most_common[0][0]} {most_common[1][0]}"
    print(f"📊 [App Matching Logic] Primary Subject Keyword Extracted: '{keyword}'")
    return keyword

def search_vercel_cloud_bridge(keyword):
    """
    অপশন ১: Vercel Cloud Bridge API Connector
    গিটহাব সিক্রেট্সে VERCEL_BRIDGE_URL যুক্ত থাকলে তা Vercel সার্ভিস মেক দিয়ে আসল আনব্লকড ডাকডাকগো মেমরির ছবি আনবে
    """
    vercel_endpoint = os.environ.get("VERCEL_BRIDGE_URL")
    if not vercel_endpoint:
        return []
    try:
        print(f"🌉 [Option 1: Vercel Bridge API] Querying Vercel Serverless DDG for: '{keyword}'...")
        r = requests.get(f"{vercel_endpoint}?q={urllib.parse.quote(keyword)}", timeout=8)
        if r.status_code == 200:
            data = r.json()
            images = data.get("images", [])
            print(f"✅ Vercel Cloud Bridge returned {len(images)} authentic DuckDuckGo images!")
            return images
    except Exception as e:
        print(f"Vercel Bridge Notice: {e}")
    return []

def search_wikimedia_images(keyword, max_results=20):
    """
    উইকিমিডিয়া পাবলিক ওপেন সোর্স REST এপিআই (গিটহাবের কোন ডাটা আইপি কখোনো ব্লক খায় না!)
    """
    try:
        url = "https://commons.wikimedia.org/w/api.php"
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"filetype:bitmap {keyword} NBA basketball",
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

def scrape_images_triple_pipeline(title, body_text, embedded_photos, max_results=30):
    candidates = []
    
    #১. সংবাদ ইউআরএল পেজ এর প্রফেশনাল মেটা অরিজিনাল কভার ছবি 
    for hero_p in embedded_photos:
        candidates.append(hero_p)
        
    subject = get_primary_keyword_app_logic(body_text)

    #২. অপশন ১ - Vercel Cloud Bridge সংযোগ (যদি ভিইআরসেল লিঙ্ক সেটিংস সিক্রেট এ দেওয়া থাকে)
    vercel_pics = search_vercel_cloud_bridge(subject)
    candidates.extend(vercel_pics)

    #৩. উইকিমিডিয়া ওপেন পাবলিক মেটা সোর্স ইন্টিগ্রেশন (১০০% আইপি ব্লকিং ফ্রী)
    if len(candidates) < 8:
        print(f"🌐 Fetching Unblocked Public Wikimedia Images for: '{subject}'...")
        wiki_pics = search_wikimedia_images(subject, max_results=15)
        candidates.extend(wiki_pics)

    return list(dict.fromkeys(candidates))

def filter_and_clean_downloaded_images(images_dir):
    """
    সর্বজনীন ফিল্টার: সাইজ, পিক্সেল রেজোলিউশন, অতিরিক্ত টেক্সট বোটেল ও অনভিপ্রেত ইমেজ মেমোরি ফাইল ফায়ার ক্লিনার
    """
    print("🧹 [Dynamic Smart Filter] Clearing irrelevant icons, ads and small size visuals...")
    valid_count = 0
    all_files = [f for f in os.listdir(images_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
    
    for fname in all_files:
        fpath = os.path.join(images_dir, fname)
        try:
            file_size = os.path.getsize(fpath)
            if file_size < 12288: # 12 KB
                os.remove(fpath)
                continue
                
            with Image.open(fpath) as img:
                w, h = img.size
                
                if w < 380 or h < 280:
                    img.close()
                    os.remove(fpath)
                    continue
                    
                aspect_ratio = w / float(h)
                if aspect_ratio < 0.45 or aspect_ratio > 2.6:
                    img.close()
                    os.remove(fpath)
                    continue
                    
                if img.mode == 'RGB':
                    stat = ImageStat.Stat(img)
                    if sum(stat.stddev) < 14: 
                        img.close()
                        os.remove(fpath)
                        continue
                        
            valid_count += 1
        except Exception:
            try: os.remove(fpath)
            except: pass
            
    print(f"✨ Post-Download Cleaning Complete! Retained {valid_count} high-quality basketball assets.")

def process_dynamic_thumbnail(images_dir, output_path):
    all_files = [f for f in os.listdir(images_dir) if f.lower().endswith(('.jpg','.jpeg','.png'))]
    if not all_files: return
    
    wide_images = []
    for f in all_files:
        try:
            with Image.open(os.path.join(images_dir, f)) as iobj:
                w, h = iobj.size
                if 1.6 <= w/h <= 1.9: wide_images.append(os.path.join(images_dir, f))
        except: pass

    try:
        if wide_images:
            Image.open(random.choice(wide_images)).convert("RGB").resize((1920,1080)).save(output_path, quality=95)
        else:
            Image.open(os.path.join(images_dir, random.choice(all_files))).convert("RGB").resize((1920,1080)).save(output_path, quality=95)
    except: pass

def clear_temporary_workspace(ws_dir):
    try:
        for fname in ["audio.mp3", "subtitles.srt", "temp_slider.txt", "temp_output.mp4", "output_video.mp4", "thumbnail.jpg"]:
            fpath = os.path.join(ws_dir, fname)
            if os.path.exists(fpath): os.remove(fpath)

        for folder_name in ["images", "processed_frames", "rendered_clips"]:
            target_path = os.path.join(ws_dir, folder_name)
            os.makedirs(target_path, exist_ok=True)
            for inner in os.listdir(target_path):
                os.remove(os.path.join(target_path, inner))
    except: pass

def render_zoom_segment_by_ffmpeg(clip_index, segment_duration, input_img_path, output_segment_path):
    frame_count = max(int(segment_duration * 25), 10)
    
    effect_style = clip_index % 3
    if effect_style == 0:
        lens_filter = f"zoompan=z='zoom+0.0015':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frame_count}:s=1920x1080:fps=25"
    elif effect_style == 1:
        lens_filter = f"zoompan=z='1.03+0.001*in':x='iw/2-(iw/zoom/2)':y='0':d={frame_count}:s=1920x1080:fps=25"
    else:
        lens_filter = f"zoompan=z='1.03+0.001*in':x='iw/2-(iw/zoom/2)':y='ih-(ih/zoom)':d={frame_count}:s=1920x1080:fps=25"
    
    cmd_arguments = [
        "ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", 
        "-loop", "1", "-framerate", "25", "-i", input_img_path, "-t", str(segment_duration), 
        "-vf", lens_filter, "-c:v", "libx264", "-preset", "ultrafast", 
        "-tune", "zerolatency", "-pix_fmt", "yuv420p", output_segment_path
    ]
    subprocess.run(cmd_arguments, check=True)
    return output_segment_path

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
    target_imgdir = os.path.join(wkspace, 'images')
    targ_pcdir = os.path.join(wkspace, 'processed_frames')
    targ_vfrmdir = os.path.join(wkspace, 'rendered_clips')
    
    blocked_inside_words = [bk.strip().lower() for bk in user_settings["exclude_body_keywords"].split(",") if bk.strip()]
    require_wc = user_settings.get("min_word_count", 150)

    for track_loop_counter, finalizer_target in enumerate(final_action_items):
        vid_ttl, lns = finalizer_target.get("title", ""), finalizer_target.get("link", "")
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
        os.makedirs(target_imgdir, exist_ok=True)
        os.makedirs(targ_pcdir, exist_ok=True)
        os.makedirs(targ_vfrmdir, exist_ok=True)

        try:
            print("Encoding Edge-TTS Audio and generating SRT timing anchors...")
            path_mp3 = os.path.join(wkspace, "audio.mp3")
            path_srt = os.path.join(wkspace, "subtitles.srt")
            
            asyncio.run(generate_voice_and_subtitles(text_chunk_collected, user_settings["voice"], path_mp3, path_srt))
            calc_tlength = get_audio_duration(path_mp3)

            # ছবি এক্সট্র্যাক্ট পাইপলাইন ৩ লেয়ার সমন্বিত সিস্টেম
            candidate_image_urls = scrape_images_triple_pipeline(vid_ttl, text_chunk_collected, embedded_page_photos, max_results=30)

            succesfully_got_downloads = 0
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
                'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
            }

            for image_link in candidate_image_urls:
                try:
                    rd = requests.get(image_link, timeout=5, headers=headers)
                    if rd.status_code == 200 and len(rd.content) > 10240: 
                        with open(os.path.join(target_imgdir, f"imv_dw{succesfully_got_downloads:03d}.jpg"), 'wb') as fgxv: 
                            fgxv.write(rd.content)
                        succesfully_got_downloads += 1
                except: pass

                if succesfully_got_downloads >= 20:
                    break

            filter_and_clean_downloaded_images(target_imgdir)

            if len(os.listdir(target_imgdir)) < 5:
                for idx, fallback_url in enumerate(VERIFIED_BASKETBALL_STOCKS):
                    try:
                        res = requests.get(fallback_url, timeout=5)
                        if res.status_code == 200:
                            with open(os.path.join(target_imgdir, f"imv_fb_{idx:03d}.jpg"), 'wb') as fb_f:
                                fb_f.write(res.content)
                    except: pass

            dflocst = sorted([pzbv for pzbv in os.listdir(target_imgdir) if pzbv.endswith(('.jpg','.jpeg','.png'))])
            print(f"📊 Download Process Complete! Retained {len(dflocst)} verified NBA basketball images.")

            if not dflocst: 
                print("Missing visual components! Skipping target."); continue

            print("Designing Blurred side padded HD 1080p graphics Canvas...")
            process_dynamic_thumbnail(target_imgdir, os.path.join(wkspace, "thumbnail.jpg"))

            for p_file in dflocst:
                try:
                    with Image.open(os.path.join(target_imgdir, p_file)) as obimgstrm:
                        base_rgb_convert = obimgstrm.convert('RGB')
                        im_w, im_h = base_rgb_convert.size
                        
                        if (im_w / im_h) < 1.7:
                            blurred_bg = base_rgb_convert.resize((1920, 1080)).filter(ImageFilter.GaussianBlur(20))
                            new_fit_width = int(1080 * (im_w / im_h))
                            sharp_fg = base_rgb_convert.resize((new_fit_width, 1080))
                            blurred_bg.paste(sharp_fg, ((1920 - new_fit_width) // 2, 0))
                            final_output_layer = blurred_bg
                        else: 
                            final_output_layer = base_rgb_convert.resize((1920, 1080))
                            
                        final_output_layer.save(os.path.join(targ_pcdir, f"pf_{p_file}"), quality=90)
                except: pass

            pil_rendered_list = sorted(os.listdir(targ_pcdir))
            if not pil_rendered_list: continue

            sentence_timers = get_sentence_timestamps(path_srt)
            pil_frames_len = len(pil_rendered_list)
            
            if not sentence_timers: 
                sentence_timers = [u_item * (calc_tlength / pil_frames_len) for u_item in range(pil_frames_len)]
            elif sentence_timers[0] > 0.1: 
                sentence_timers.insert(0, 0.0)
            else: 
                sentence_timers[0] = 0.0
            sentence_timers.append(calc_tlength)
            total_n_segments = len(sentence_timers) - 1

            lines_for_slider_doc = []
            print(f"Rendering {total_n_segments} unique video clip scenes matching individual sentence audio using FFmpeg...")

            with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as thex:
                rendered_segment_tasks = []
                for sg_ix in range(total_n_segments):
                    s_gap = sentence_timers[sg_ix+1] - sentence_timers[sg_ix]
                    if s_gap <= 0: continue
                    img_f = os.path.join(targ_pcdir, pil_rendered_list[sg_ix % len(pil_rendered_list)])
                    output_v_frag = os.path.join(targ_vfrmdir, f"seg_{sg_ix:04d}.mp4")
                    rendered_segment_tasks.append(thex.submit(render_zoom_segment_by_ffmpeg, sg_ix, s_gap, img_f, output_v_frag))
                    
                for task_obj in rendered_segment_tasks: 
                    absolute_clip_path = os.path.abspath(task_obj.result()).replace("\\", "/")
                    lines_for_slider_doc.append(f"file '{absolute_clip_path}'")

            tmpsldr_txt_path = os.path.join(wkspace, "temp_slider.txt")
            with open(tmpsldr_txt_path, "w", encoding="utf-8") as fw12z: fw12z.write("\n".join(lines_for_slider_doc))
            
            raw_tmp_output = os.path.join(wkspace, "temp_output.mp4")
            fully_finalized_output = os.path.join(wkspace, "output_video.mp4")
            
            print("Combining audio and hardcoded subtitles into final video file...")
            subprocess.run(["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-safe", "0", "-f", "concat", "-i", os.path.abspath(tmpsldr_txt_path).replace("\\", "/"), "-i", os.path.abspath(path_mp3).replace("\\", "/"), "-c:v", "copy", "-c:a", "copy", "-shortest", os.path.abspath(raw_tmp_output).replace("\\", "/")], check=True)

            clx_pri = hex_to_ass_color(user_settings["font_color"], 1.0)
            clx_bkg = hex_to_ass_color(user_settings["bg_color"], user_settings.get("bg_opacity", 0.5))
            stylstr_for_subs = f"FontName=Arial,FontSize={user_settings['font_size']},PrimaryColour={clx_pri},BackColour={clx_bkg},BorderStyle={user_settings['border_style']},Outline=2,Shadow=1,Alignment=2,MarginV={user_settings['margin_v']}"

            absolute_srt_path = os.path.abspath(path_srt).replace("\\", "/")
            tclmstr_subtitles_filter = f"subtitles='{absolute_srt_path}':force_style='{stylstr_for_subs}'"

            subs_cmd = [
                "ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", 
                "-i", os.path.abspath(raw_tmp_output).replace("\\", "/"), 
                "-vf", tclmstr_subtitles_filter, 
                "-c:v", "libx264", "-crf", "18", "-preset", "ultrafast", "-tune", "zerolatency",
                "-c:a", "copy", os.path.abspath(fully_finalized_output).replace("\\", "/")
            ]
            subprocess.run(subs_cmd, check=True)
            
            safe_upload_to_youtube(fully_finalized_output, os.path.join(wkspace, "thumbnail.jpg"), vid_ttl, f"Complete Highlights Recap: {vid_ttl}\nGenerated automatically via AI Cloud System.")
            
            with open("processed_urls.txt", "a", encoding="utf-8") as fwx_docv: fwx_docv.write(lns+"\n")
            print("================ 🎯 Complete Workflow Operations executed successfully seamlessly! 💯 ================\n")

        except Exception as errp: traceback.print_exc()

if __name__ == "__main__":
    process_primary_automation_loop()
