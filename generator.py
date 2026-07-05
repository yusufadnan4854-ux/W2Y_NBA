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
from PIL import Image, ImageFilter
from concurrent.futures import ThreadPoolExecutor
import feedparser  
import edge_tts

try:
    from moviepy import ImageClip
    MOVIEPY_V2 = True
except ImportError:
    from moviepy.editor import ImageClip
    MOVIEPY_V2 = False

GENERIC_SPORTS_FALLBACKS = [
    "https://images.unsplash.com/photo-1546519638-68e109498ffc?w=1920&q=80",  
    "https://images.unsplash.com/photo-1519766304817-4f37bda74a27?w=1920&q=80",  
    "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?w=1920&q=80",  
    "https://images.unsplash.com/photo-1461896836934-ffe607ba8211?w=1920&q=80",  
    "https://images.unsplash.com/photo-1517649763962-0c623066013b?w=1920&q=80",  
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
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(url, headers=headers, timeout=15)
    soup = BeautifulSoup(response.text, 'html.parser')
    cleaned_paragraphs = []
    
    unwanted_phrases = ["follow", "read more", "cookies", "subscribe", "social media information", "like our page", "bgn community post", "featured in the linc", "the linc!"]
    
    for p in soup.find_all('p'):
        text = p.get_text().strip()
        if len(text) < 15 or any(k in text.lower() for k in unwanted_phrases): 
            continue
        cleaned_paragraphs.append(text)
        
    return "\n\n".join(cleaned_paragraphs)

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

# 🌟 গুগলের অফিশিয়াল ইমেজ সার্চ এপিআই (Google Custom Search API - No blocks, maximum relevant results!)
def search_google_images(keyword, max_results=20):
    api_key = os.environ.get("GOOGLE_API_KEY")
    cse_id = os.environ.get("GOOGLE_CSE_ID")
    
    if not api_key or not cse_id:
        print("Google CSE credentials missing. Shifting to alternative engines.")
        return []
        
    print(f"Searching Google Images for: '{keyword}'...")
    url = "https://www.googleapis.com/customsearch/v1"
    
    urls = []
    try:
        # ১ম ১০টি ছবি সার্চ 
        params = {
            "key": api_key,
            "cx": cse_id,
            "q": keyword,
            "searchType": "image",
            "num": min(max_results, 10),
            "imgSize": "large"
        }
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            items = r.json().get("items", [])
            urls.extend([item.get("link") for item in items if item.get("link")])
            
        # ২য় ১০টি ছবি সার্চ (প্রয়োজন হলে)
        if max_results > 10 and len(urls) >= 10:
            params["start"] = 11
            params["num"] = min(max_results - 10, 10)
            r = requests.get(url, params=params, timeout=10)
            if r.status_code == 200:
                items = r.json().get("items", [])
                urls.extend([item.get("link") for item in items if item.get("link")])
                
        print(f"Google Images successfully extracted {len(urls)} target resources.")
        return urls
    except Exception as e:
        print(f"Google Image Search failed: {e}")
    return []

def search_bing_images_fallback(keyword, max_results=20):
    headers = {"User-Agent": "Mozilla/5.0"}
    url = f"https://www.bing.com/images/search?q={urllib.parse.quote(keyword)}&FORM=HDRSC2"
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            urls = re.findall(r'"murl":"(http[^"]+)"', r.text)
            unique_urls = list(dict.fromkeys(urls))
            return unique_urls[:max_results]
    except: pass
    return []

def fallback_wikimedia_images(keyword, max_results=20):
    try:
        url = "https://commons.wikimedia.org/w/api.php"
        params = {
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": f"filetype:bitmap {keyword}", "gsrlimit": max_results,
            "prop": "imageinfo", "iiprop": "url"
        }
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            pages = r.json().get("query", {}).get("pages", {})
            return [p["imageinfo"][0]["url"] for p in pages.values() if p.get("imageinfo")]
    except: pass
    return []

def scrape_images(keyword, max_results=20):
    # ১. প্রথমে অফিশিয়াল গুগল ইমেজ দিয়ে ট্রাই করবে (সেরা কোয়ালিটি ও নো-ব্লক গ্যারান্টি)
    urls = search_google_images(keyword, max_results=max_results)
    
    # ২. গুগল এপিআই কি না থাকলে বা লিমিট শেষ হলে বিং ইমেজ ট্রাই করবে 
    if not urls:
        urls = search_bing_images_fallback(keyword, max_results=max_results)
        
    # ৩. বিং ফেইল করলে উইকিমিডিয়া কমন্স দিয়ে ট্রাই করবে 
    if not urls:
        urls = fallback_wikimedia_images(keyword, max_results=max_results)
        
    return urls

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
    frame_count = int(segment_duration * 30)
    
    effect_style = clip_index % 3
    if effect_style == 0:
        lens_filter = f"zoompan=z='zoom+0.001':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frame_count}:s=1920x1080,framerate=30"
    elif effect_style == 1:
        lens_filter = f"zoompan=z='1.02+0.001*in':x='iw/2-(iw/zoom/2)':y='0':d={frame_count}:s=1920x1080,framerate=30"
    else:
        lens_filter = f"zoompan=z='1.02+0.001*in':x='iw/2-(iw/zoom/2)':y='ih-(ih/zoom)':d={frame_count}:s=1920x1080,framerate=30"
    
    cmd_arguments = [
        "ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", 
        "-loop", "1", "-i", input_img_path, "-t", str(segment_duration), 
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

    pack = {
        'snippet': {'title': title[:98], 'description': video_description, 'categoryId': '17'}, 
        'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}
    }
    target_job = google_cloud_instance.videos().insert(part="snippet,status", body=pack, media_body=MediaFileUpload(video_full_path, resumable=True, mimetype="video/mp4"))
    completed_exec = target_job.execute()
    newly_deployed_id = completed_exec.get('id')
    
    print(f"Mission uploaded successfully! ID: {newly_deployed_id}")

    if os.path.exists(thumb_full_path):
        google_cloud_instance.thumbnails().set(videoId=newly_deployed_id, media_body=MediaFileUpload(thumb_full_path)).execute()
        print("Associated verified display cover picture verified added effectively.\n")


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

    wkspace = os.path.abspath(os.path.join(os.getcwd(), 'workspace'))
    target_imgdir = os.path.join(wkspace, 'images')
    targ_pcdir = os.path.join(wkspace, 'processed_frames')
    targ_vfrmdir = os.path.join(wkspace, 'rendered_clips')
    
    blocked_inside_words = [bk.strip().lower() for bk in user_settings["exclude_body_keywords"].split(",") if bk.strip()]
    require_wc = user_settings.get("min_word_count", 150)

    for track_loop_counter, finalizer_target in enumerate(final_action_items):
        vid_ttl, lns = finalizer_target.get("title", ""), finalizer_target.get("link", "")
        print(f"\n[{track_loop_counter+1}/{len(final_action_items)}] Valid Target Found: >> {vid_ttl}")

        text_chunk_collected = scrape_article(lns)
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
            print("Encoding TTS Native Stream Engine via remote server structure accurately...")
            path_mp3 = os.path.join(wkspace, "audio.mp3")
            path_srt = os.path.join(wkspace, "subtitles.srt")
            
            asyncio.run(generate_voice_and_subtitles(text_chunk_collected, user_settings["voice"], path_mp3, path_srt))
            
            calc_tlength = get_audio_duration(path_mp3)
            pics_limit_range = 30 if calc_tlength > 240.0 else 18

            first_subject_arrays = re.findall(r'\b[A-Z][a-z]{3,}\b', text_chunk_collected)
            active_smart_lookup_word = f"{first_subject_arrays[0]} {first_subject_arrays[1]}" if len(first_subject_arrays) >= 2 else "Sports match highlights action field"
            
            raw_unlinked_pic_pointers = scrape_images(active_smart_lookup_word, max_results=pics_limit_range)

            succesfully_got_downloads = 0
            for purelink in raw_unlinked_pic_pointers:
                try:
                    rd_dt_rsv = requests.get(purelink, timeout=5)
                    if rd_dt_rsv.status_code == 200:
                        with open(os.path.join(target_imgdir, f"imv_dw{succesfully_got_downloads:03d}.jpg"), 'wb') as fgxv: 
                            fgxv.write(rd_dt_rsv.content)
                            succesfully_got_downloads += 1
                except: pass

            dflocst = sorted([pzbv for pzbv in os.listdir(target_imgdir) if pzbv.endswith(('.jpg','.jpeg','.png'))])
            if not dflocst: 
                print("Missing total graphical assets globally. Skipping current target... "); continue

            print("Constructing display layout aspects mapping accurately handling dimensions over 16:9 1080p full configurations...")
            process_dynamic_thumbnail(target_imgdir, os.path.join(wkspace, "thumbnail.jpg"))

            for p_file in dflocst:
                try:
                    with Image.open(os.path.join(target_imgdir, p_file)) as obimgstrm:
                        base_rgb_convert = obimgstrm.convert('RGB')
                        im_w, im_h = base_rgb_convert.size
                        
                        if (im_w / im_h) < 1.7:
                            blurred_bg = base_rgb_convert.resize((1920, 1080)).filter(ImageFilter.GaussianBlur(15))
                            new_fit_width = int(1080 * (im_w / im_h))
                            sharp_fg = base_rgb_convert.resize((new_fit_width, 1080))
                            blurred_bg.paste(sharp_fg, ((1920 - new_fit_width) // 2, 0))
                            final_output_layer = blurred_bg
                        else: 
                            final_output_layer = base_rgb_convert.resize((1920, 1080))
                            
                        final_output_layer.save(os.path.join(targ_pcdir, f"pf_{p_file}"), quality=85)
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
            
            print(f"Assigning Fast Direct Encoding Native Modules building completely cleanly perfectly over core engines logically...")

            with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as thex:
                rendered_segment_tasks = []
                for sg_ix in range(total_n_segments):
                    s_gap = sentence_timers[sg_ix+1] - sentence_timers[sg_ix]
                    img_f = os.path.join(targ_pcdir, pil_rendered_list[sg_ix % len(pil_rendered_list)])
                    output_v_frag = os.path.join(targ_vfrmdir, f"segcxvsxbvzvfvfbbbccsczxbxffzfvdczxfcdxdzfdfxvfxxcbvvsfxzbsvcbscxxzxzbzxvvvxdbsscdvfddvfbfvdscbzscvxxsdczvdccszxd_{sg_ix:04d}.mp4")
                    rendered_segment_tasks.append(thex.submit(render_zoom_segment_by_ffmpeg, sg_ix, s_gap, img_f, output_v_frag))
                    
                for task_obj in rendered_segment_tasks: 
                    absolute_clip_path = os.path.abspath(task_obj.result()).replace("\\", "/")
                    lines_for_slider_doc.append(f"file '{absolute_clip_path}'")

            tmpsldr_txt_path = os.path.join(wkspace, "temp_slider.txt")
            with open(tmpsldr_txt_path, "w", encoding="utf-8") as fw12z: fw12z.write("\n".join(lines_for_slider_doc))
            
            raw_tmp_output = os.path.join(wkspace, "temp_output.mp4")
            fully_finalized_output = os.path.join(wkspace, "output_video.mp4")
            
            print("Mixing layers completely perfectly safe bypassing block issues dynamically...")
            subprocess.run(["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-safe", "0", "-f", "concat", "-i", os.path.abspath(tmpsldr_txt_path).replace("\\", "/"), "-i", os.path.abspath(path_mp3).replace("\\", "/"), "-c:v", "copy", "-c:a", "copy", "-shortest", os.path.abspath(raw_tmp_output).replace("\\", "/")], check=True)

            clx_pri = hex_to_ass_color(user_settings["font_color"], 1.0)
            clx_bkg = hex_to_ass_color(user_settings["bg_color"], user_settings.get("bg_opacity", 0.5))
            stylstr_for_subs = f"FontName=Arial,FontSize={user_settings['font_size']},PrimaryColour={clx_pri},BackColour={clx_bkg},BorderStyle={user_settings['border_style']},Outline=2,Shadow=1,Alignment=2,MarginV={user_settings['margin_v']}"

            # FIXED THE LINUX SUBTITLE PATH BUG BY ESCAPING PROPERLY AND CONVERTING TO ABSOLUTE FORWARD SLASHES
            absolute_srt_path = os.path.abspath(path_srt).replace("\\", "/")
            tclmstr_subtitles_filter = f"subtitles='{absolute_srt_path}':force_style='{stylstr_for_subs}'"

            subs_cmd = [
                "ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", 
                "-i", os.path.abspath(raw_tmp_output).replace("\\", "/"), 
                "-vf", tclmstr_subtitles_filter, 
                "-c:v", "libx264", "-crf", "18", "-preset", "ultrafast", 
                "-c:a", "copy", os.path.abspath(fully_finalized_output).replace("\\", "/")
            ]
            subprocess.run(subs_cmd, check=True)
            
            safe_upload_to_youtube(fully_finalized_output, os.path.join(wkspace, "thumbnail.jpg"), vid_ttl, f"Complete Highlights Recap: {vid_ttl}\nGenerated automatically via AI Cloud System.")
            
            with open("processed_urls.txt", "a", encoding="utf-8") as fwx_docv: fwx_docv.write(lns+"\n")
            print("================ 🎯 Entire operation pipeline handled seamlessly efficiently generating complete outcomes directly efficiently 💯 ================\n")

        except Exception as errp: traceback.print_exc()

if __name__ == "__main__":
    process_primary_automation_loop()
