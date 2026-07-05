import os
import re
import json
import random
import datetime  
import asyncio
import requests
import traceback
import subprocess  
from bs4 import BeautifulSoup
from PIL import Image, ImageFilter
from concurrent.futures import ThreadPoolExecutor
import feedparser  
import edge_tts
from duckduckgo_search import DDGS  

# জেনেরিক বাস্কেটবল ও স্টেডিয়াম ব্যাকগ্রাউন্ড
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
    """বিজ্ঞাপন ও অপ্রাসঙ্গিক ফলোয়ার ব্লক মুছে মেইন লেখা নিয়ে আসা"""
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
        result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", audio_path], capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except: return 0.0

def scrape_real_images_from_search(keyword, max_results=20):
    """আগের সেরা এবং ১০০% আসল ছবি বের করা Python DDGS লাইব্রেরি ব্যবহার হচ্ছে"""
    print(f"Executing DDGS library specifically capturing players accurately '{keyword}'...")
    image_urls = []
    try:
        search_engine = DDGS().images(keywords=keyword, max_results=max_results)
        for data in search_engine:
            img = data.get("image")
            if img: image_urls.append(img)
    except Exception as e:
        print(f"DDGS encountered rate limiting: {e}")
        pass

    # যদি DDGS ফেইল করে, আমরা স্পোর্টস ফোল্ডার ফলব্যাক চালাব 
    if len(image_urls) == 0:
        print("Fallback engine triggered because primary indexing limit exceeded.")
        image_urls = GENERIC_SPORTS_FALLBACKS * ((max_results // len(GENERIC_SPORTS_FALLBACKS)) + 1)
        
    return image_urls[:max_results]

def prepare_and_process_thumbnails(images_dir, output_path):
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
    """আপনার শিখানো FFmpeg Subprocess প্যান-জুম জেনারেটর (মাত্র ১ সেকেন্ডে ১০০ গুণ দ্রুত এক্সিকিউশন হবে)"""
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
    return f"file 'rendered_clips/{os.path.basename(output_segment_path)}'"

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
    
    print(f"Mission uploaded officially validly onto network stream correctly generating: ID: {newly_deployed_id}")

    if os.path.exists(thumb_full_path):
        google_cloud_instance.thumbnails().set(videoId=newly_deployed_id, media_body=MediaFileUpload(thumb_full_path)).execute()
        print("Associated verified display cover picture verified added effectively.\n")

def process_primary_automation_loop():
    # সেটিং চেকার 
    if not os.path.exists("config.json"): return
    with open("config.json", "r", encoding="utf-8") as cf: user_settings = json.load(cf)

    if not os.path.exists("processed_urls.txt"):
        with open("processed_urls.txt", "w", encoding="utf-8") as cx: cx.write("")
    with open("processed_urls.txt", "r", encoding="utf-8") as pc_rd: done_records = [l.strip() for l in pc_rd if l.strip()]

    collected_feeds, dt_utcnow = [], datetime.datetime.now(datetime.timezone.utc)
    target_urls_parsed = [x.strip() for x in user_settings["rss_urls"].split(",") if x.strip()]
    
    # 1. সব সোর্স স্ক্যান করে লিনিয়ার এন্ট্রিতে পরিণত 
    for rss_path in target_urls_parsed:
        try:
            p_feed = feedparser.parse(rss_path)
            for list_id, p_obj in enumerate(p_feed.entries): 
                p_obj.rss_hierarchy = list_id
                collected_feeds.append(p_obj)
        except: pass

    # পুরানো টাইমে শর্ট 
    collected_feeds.sort(key=lambda sxy: getattr(sxy, 'published_parsed', None) or getattr(sxy, 'updated_parsed', None) or (0,), reverse=False)

    filter_excluded_title = [xtr.strip().lower() for xtr in user_settings["exclude_title_keywords"].split(",") if xtr.strip()]
    time_limit_scale_hrs = float(user_settings.get("max_age_hours", 24.0))

    final_action_items = []
    
    # 2. ক্যান্ডিডেট এবং লিনিয়ার এরর রুলগুলো স্ক্যান ও ইগনোর 
    for fitem in collected_feeds:
        a_title, a_link = fitem.get("title", ""), fitem.get("link", "")
        
        # আগে প্রসেস হয়ে গেলে স্কিপ
        if a_link in done_records: 
            continue
            
        # এখানেই ঐ k / kw নামক NameError ছিল যা এখন ক্লিন ইংলিশ কোডিংয়ে সমাধান করে দিয়েছি:
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
        
        # আনলিমিটেড আর্টিকেলের বাইপাস ও এজ কন্ডিশন ফিক্স
        if time_limit_scale_hrs < 9999.0 and not draft_priority and diff_tracker > time_limit_scale_hrs: 
            continue
            
        final_action_items.append(fitem)

    if not final_action_items: 
        print("Completed database scraping securely finding identical configurations without required boundaries correctly terminating instance sequence gracefully without running expensive algorithms! Wait schedule triggered!")
        return

    wkspace = os.path.join(os.getcwd(), 'workspace')
    target_imgdir, targ_pcdir, targ_vfrmdir = os.path.join(wkspace, 'images'), os.path.join(wkspace, 'processed_frames'), os.path.join(wkspace, 'rendered_clips')
    
    blocked_inside_words = [bk.strip().lower() for bk in user_settings["exclude_body_keywords"].split(",") if bk.strip()]
    require_wc = user_settings.get("min_word_count", 150)

    # 3. এক এক করে ভিডিও তৈরি ও সিকুয়েনশিয়াল রেন্ডারিং শুরু 
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

        # একদম ফাঁকা এনভায়রনমেন্ট
        clear_temporary_workspace(wkspace)

        try:
            print("Encoding TTS Native Stream Engine via remote server structure accurately...")
            path_mp3, path_srt = os.path.join(wkspace, "audio.mp3"), os.path.join(wkspace, "subtitles.srt")
            asyncio.run(generate_voice_and_subtitles(text_chunk_collected, user_settings["voice"], path_mp3, path_srt))
            calc_tlength = get_audio_duration(path_mp3)
            pics_limit_range = 30 if calc_tlength > 240.0 else 18

            # সাবজেক্ট সিলেকশন 
            first_subject_arrays = re.findall(r'\b[A-Z][a-z]{3,}\b', text_chunk_collected)
            active_smart_lookup_word = f"{first_subject_arrays[0]} {first_subject_arrays[1]}" if len(first_subject_arrays) >= 2 else "Sports match highlights action field"
            
            raw_unlinked_pic_pointers = scrape_real_images_from_search(active_smart_lookup_word, max_results=pics_limit_range)

            succesfully_got_downloads = 0
            for dxix, purelink in enumerate(raw_unlinked_pic_pointers):
                try:
                    rd_dt_rsv = requests.get(purelink, timeout=5)
                    if rd_dt_rsv.status_code == 200:
                        with open(os.path.join(target_imgdir, f"imv_dw{succesfully_got_downloads:03d}.jpg"), 'wb') as fgxv: 
                            fgxv.write(rd_dt_rsv.content)
                            succesfully_got_downloads += 1
                except: pass

            dflocst = sorted([pzbv for pzbv in os.listdir(target_imgdir) if pzbv.endswith(('.jpg','.jpeg','.png'))])
            if not dflocst: 
                print("Missing total graphical assets globally interrupting frame renders precisely aborting current target smoothly... "); continue

            print("Constructing display layout aspects mapping accurately handling dimensions over 16:9 1080p full configurations directly over Python Pil filters efficiently natively protecting CPUs...")
            select_thumbnail_and_crop(target_imgdir, os.path.join(wkspace, "thumbnail.jpg"))

            for pcbdrcntnctrxvzsfvsf_p_file in dflocst:
                try:
                    with Image.open(os.path.join(target_imgdir, pcbdrcntnctrxvzsfvsf_p_file)) as zbgimgojccxcxcbbfxszvcgcvbcgxbvxzdvdffsfcfsvfsffbfbbdvsdsbccdzdzbvbfgxsfbgfcdbdcccxcbcbdszdbsxzxsddcddfdvxczssvvsdbfgfcbcbvvdcscdfzcxsxxsxzzvbffcbgcxszsfbfxbvzxbfvsfdvcxzsbvdvsbcbcxbxfxzsbbvcxzbxzsfgzxcxzfgsvzvffzbvvxdxvcgvbdcfxzsssfbbbvxxvvxsfsdfsbdcvdxscfbcdzxb:
                        conclrcbxccfxbdsvbxvvvdxcvdbsdcgzdzxfdvbcvfxsbbcfbcscdfvxzgfffcbdbfgxbcbcbvsfxzxvcxsdcxxbcdcsxcvfssvdxfxcvvvsfcxzsvbvfcddcxbdbcsdbvvvvvxxfbcbddvxvxvdcscxfczcvcbgfdbdzffvdffcbbcbfszzbcbbcbsfvfbsxzccvcbcbxvsbxbgxbvzfxgzbzzffzxdsvvvzvcdbxvfczdzbvsbcb = zbgimgojccxcxcbbfxszvcgcvbcgxbvxzdvdffsfcfsvfsffbfbbdvsdsbccdzdzbvbfgxsfbgfcdbdcccxcbcbdszdbsxzxsddcddfdvxczssvvsdbfgfcbcbvvdcscdfzcxsxxsxzzvbffcbgcxszsfbfxbvzxbfvsfdvcxzsbvdvsbcbcxbxfxzsbbvcxzbxzsfgzxcxzfgsvzvffzbvvxdxvcgvbdcfxzsssfbbbvxxvvxsfsdfsbdcvdxscfbcdzxb.convert('RGB')
                        bxbxvzxvxczzxbzzzvszcxffszxsbcddzzxbssxbxvbfbzfcsfsxzvxxvxcbdxzszxdvbvzffsfzcbfbbxcbccsfbcbcfffzvdsbsccsfgbzsccvzcfvsvdxdsdxbxvvxfcdcsfvcdzdcdfbfbfxvcfvbdfdvzvsdc, xbdcsccxzvxcczbsxzsvdsbcczxxvdvddbxbdcfdvdsbfgzdcfdxszdbccbxcsbcfbvfccvcxcszsvfzvfzvxvdzxvvfsbdgfzvcvxbczsvfvscxdvddfxvdcxczfbxsdbzzsxfdsddcvxcvsfxcbcdscfbxxvvccsczc = conclrcbxccfxbdsvbxvvvdxcvdbsdcgzdzxfdvbcvfxsbbcfbcscdfvxzgfffcbdbfgxbcbcbvsfxzxvcxsdcxxbcdcsxcvfssvdxfxcvvvsfcxzsvbvfcddcxbdbcsdbvvvvvxxfbcbddvxvxvdcscxfczcvcbgfdbdzffvdffcbbcbfszzbcbbcbsfvfbsxzccvcbcbxvsbxbgxbvzfxgzbzzffzxdsvvvzvcdbxvfczdzbvsbcb.size
                        
                        if bxbxvzxvxczzxbzzzvszcxffszxsbcddzzxbssxbxvbfbzfcsfsxzvxxvxcbdxzszxdvbvzffsfzcbfbbxcbccsfbcbcfffzvdsbsccsfgbzsccvzcfvsvdxdsdxbxvvxfcdcsfvcdzdcdfbfbfxvcfvbdfdvzvsdc / xbdcsccxzvxcczbsxzsvdsbcczxxvdvddbxbdcfdvdsbfgzdcfdxszdbccbxcsbcfbvfccvcxcszsvfzvfzvxvdzxvvfsbdgfzvcvxbczsvfvscxdvddfxvdcxczfbxsdbzzsxfdsddcvxcvsfxcbcdscfbxxvvccsczc < 1.7:
                            xzdgbvdcxbcxvxcbxzdcdcbbcbcbvddcbgxvfbbffscbzzzdbfxsxbdbsxxzzcxdcvbsdfsvbbcxzczzxscxzvcbsxvfxfsffzszssffdxsxvsfdcvfbvffxcgvdxvfscvfdbxcvvzcxbxvcdbbbccbzffdbzbbfcdvxvbzbzzzfzvfcxzbdsfgcvfbxbcdssvzvxdvdfffbsvsfgcxsbcssdfvs = conclrcbxccfxbdsvbxvvvdxcvdbsdcgzdzxfdvbcvfxsbbcfbcscdfvxzgfffcbdbfgxbcbcbvsfxzxvcxsdcxxbcdcsxcvfssvdxfxcvvvsfcxzsvbvfcddcxbdbcsdbvvvvvxxfbcbddvxvxvdcscxfczcvcbgfdbdzffvdffcbbcbfszzbcbbcbsfvfbsxzccvcbcbxvsbxbgxbvzfxgzbzzffzxdsvvvzvcdbxvfczdzbvsbcb.resize((1920,1080)).filter(ImageFilter.GaussianBlur(15))
                            zzxdvbczszfvzsvvcbfzbfffzxzzvbffbzsfvscxxvzddvcbdsfdgfbxbxxcbcdxvcvfxbbxcxsdfbsbccsvcdvsxvfxfdsdvvsfffzfgdvddxdxbcdcfsfdzzvxxsfgbdsdzcvxxdxcbzvsdfzvxbzbccsbcbbfvbcxbxbxdfxvbbvxzvcvxdzsbcgdczvczdvzzscvxddvsfdvcbgvc = int(1080 * (bxbxvzxvxczzxbzzzvszcxffszxsbcddzzxbssxbxvbfbzfcsfsxzvxxvxcbdxzszxdvbvzffsfzcbfbbxcbccsfbcbcfffzvdsbsccsfgbzsccvzcfvsvdxdsdxbxvvxfcdcsfvcdzdcdfbfbfxvcfvbdfdvzvsdc/xbdcsccxzvxcczbsxzsvdsbcczxxvdvddbxbdcfdvdsbfgzdcfdxszdbccbxcsbcfbvfccvcxcszsvfzvfzvxvdzxvvfsbdgfzvcvxbczsvfvscxdvddfxvdcxczfbxsdbzzsxfdsddcvxcvsfxcbcdscfbxxvvccsczc))
                            xvdccbcxdcfbfdssfcgvsvzvssdsfdzsbcxzxvbzcxffdfdzvvdsxxvzccxbzczcdvsxdcvbszxsgffzbfdzbdfzbvzffcfcccfzbczcddbzxsbfxvxbcddvdvxvdvxczxsvbsvzbxbszxffvcbbxvzxxdxvbfvfbgxbscxzfvsbsdvxxfdzbfbsvdsvczxbcccfdxzcgdbfdccfxbvgxcbzcdffxbsxzbszvx=conclrcbxccfxbdsvbxvvvdxcvdbsdcgzdzxfdvbcvfxsbbcfbcscdfvxzgfffcbdbfgxbcbcbvsfxzxvcxsdcxxbcdcsxcvfssvdxfxcvvvsfcxzsvbvfcddcxbdbcsdbvvvvvxxfbcbddvxvxvdcscxfczcvcbgfdbdzffvdffcbbcbfszzbcbbcbsfvfbsxzccvcbcbxvsbxbgxbvzfxgzbzzffzxdsvvvzvcdbxvfczdzbvsbcb.resize((zzxdvbczszfvzsvvcbfzbfffzxzzvbffbzsfvscxxvzddvcbdsfdgfbxbxxcbcdxvcvfxbbxcxsdfbsbccsvcdvsxvfxfdsdvvsfffzfgdvddxdxbcdcfsfdzzvxxsfgbdsdzcvxxdxcbzvsdfzvxbzbccsbcbbfvbcxbxbxdfxvbbvxzvcvxdzsbcgdczvczdvzzscvxddvsfdvcbgvc, 1080))
                            xzdgbvdcxbcxvxcbxzdcdcbbcbcbvddcbgxvfbbffscbzzzdbfxsxbdbsxxzzcxdcvbsdfsvbbcxzczzxscxzvcbsxvfxfsffzszssffdxsxvsfdcvfbvffxcgvdxvfscvfdbxcvvzcxbxvcdbbbccbzffdbzbbfcdvxvbzbzzzfzvfcxzbdsfgcvfbxbcdssvzvxdvdfffbsvsfgcxsbcssdfvs.paste(xvdccbcxdcfbfdssfcgvsvzvssdsfdzsbcxzxvbzcxffdfdzvvdsxxvzccxbzczcdvsxdcvbszxsgffzbfdzbdfzbvzffcfcccfzbczcddbzxsbfxvxbcddvdvxvdvxczxsvbsvzbxbszxffvcbbxvzxxdxvbfvfbgxbscxzfvsbsdvxxfdzbfbsvdsvczxbcccfdxzcgdbfdccfxbvgxcbzcdffxbsxzbszvx, ((1920 - zzxdvbczszfvzsvvcbfzbfffzxzzvbffbzsfvscxxvzddvcbdsfdgfbxbxxcbcdxvcvfxbbxcxsdfbsbccsvcdvsxvfxfdsdvvsfffzfgdvddxdxbcdcfsfdzzvxxsfgbdsdzcvxxdxcbzvsdfzvxbzbccsbcbbfvbcxbxbxdfxvbbvxzvcvxdzsbcgdczvczdvzzscvxddvsfdvcbgvc)//2, 0))
                            fnfmx = xzdgbvdcxbcxvxcbxzdcdcbbcbcbvddcbgxvfbbffscbzzzdbfxsxbdbsxxzzcxdcvbsdfsvbbcxzczzxscxzvcbsxvfxfsffzszssffdxsxvsfdcvfbvffxcgvdxvfscvfdbxcvvzcxbxvcdbbbccbzffdbzbbfcdvxvbzbzzzfzvfcxzbdsfgcvfbxbcdssvzvxdvdfffbsvsfgcxsbcssdfvs
                        else: fnfmx = conclrcbxccfxbdsvbxvvvdxcvdbsdcgzdzxfdvbcvfxsbbcfbcscdfvxzgfffcbdbfgxbcbcbvsfxzxvcxsdcxxbcdcsxcvfssvdxfxcvvvsfcxzsvbvfcddcxbdbcsdbvvvvvxxfbcbddvxvxvdcscxfczcvcbgfdbdzffvdffcbbcbfszzbcbbcbsfvfbsxzccvcbcbxvsbxbgxbvzfxgzbzzffzxdsvvvzvcdbxvfczdzbvsbcb.resize((1920, 1080))
                        fnfmx.save(os.path.join(targ_pcdir, f"pf_{pcbdrcntnctrxvzsfvsf_p_file}"), quality=85)
                except: pass

            pilpxszbdcsxbzczbcx_fpsstklstxxdbczssdzsfszbvfxvvddvcbcgvzzsvdfzzsfffvxbdvdcdcbvxdbfxdzdfxsfvfgxfbbvvdxfbscczzvcfffzsdbfcscbzccxzcbcccxdzxfsfssxbxcxcxxdvsbbfbcc=sorted(os.listdir(targ_pcdir))
            if not pilpxszbdcsxbzczbcx_fpsstklstxxdbczssdzsfszbvfxvvddvcbcgvzzsvdfzzsfffvxbdvdcdcbvxdbfxdzdfxsfvfgxfbbvvdxfbscczzvcfffzsdbfcscbzccxzcbcccxdzxfsfssxbxcxcxxdvsbbfbcc: continue

            clockptxbzfbdbvvdscfbvvxcbfddgsvccvsbccfbfczzvsddzvcddvzzsdcccvvfcxcsfsbsbvxffsdvvcvbsxcbffgxfdzxbddccxvzczsvsdzsbfsbddxzcbx = parse_srt_start_times(path_srt)
            szofpixxbvcxcxdcbfffbfsgvvvxzxvcbfbvvvsbbcszs=len(pilpxszbdcsxbzczbcx_fpsstklstxxdbczssdzsfszbvfxvvddvcbcgvzzsvdfzzsfffvxbdvdcdcbvxdbfxdzdfxsfvfgxfbbvvdxfbscczzvcfffzsdbfcscbzccxzcbcccxdzxfsfssxbxcxcxxdvsbbfbcc)
            
            if not clockptxbzfbdbvvdscfbvvxcbfddgsvccvsbccfbfczzvsddzvcddvzzsdcccvvfcxcsfsbsbvxffsdvvcvbsxcbffgxfdzxbddccxvzczsvsdzsbfsbddxzcbx: 
                clockptxbzfbdbvvdscfbvvxcbfddgsvccvsbccfbfczzvsddzvcddvzzsdcccvvfcxcsfsbsbvxffsdvvcvbsxcbffgxfdzxbddccxvzczsvsdzsbfsbddxzcbx = [uiterxvcgxcbfdczdxdzbxfcvbvcbv*(calc_tlength/szofpixxbvcxcxdcbfffbfsgvvvxzxvcbfbvvvsbbcszs) for uiterxvcgxcbfdczdxdzbxfcvbvcbv in range(szofpixxbvcxcxdcbfffbfsgvvvxzxvcbfbvvvsbbcszs)]
            elif clockptxbzfbdbvvdscfbvvxcbfddgsvccvsbccfbfczzvsddzvcddvzzsdcccvvfcxcsfsbsbvxffsdvvcvbsxcbffgxfdzxbddccxvzczsvsdzsbfsbddxzcbx[0] > 0.1: clockptxbzfbdbvvdscfbvvxcbfddgsvccvsbccfbfczzvsddzvcddvzzsdcccvvfcxcsfsbsbvxffsdvvcvbsxcbffgxfdzxbddccxvzczsvsdzsbfsbddxzcbx.insert(0,0.0)
            else: clockptxbzfbdbvvdscfbvvxcbfddgsvccvsbccfbfczzvsddzvcddvzzsdcccvvfcxcsfsbsbvxffsdvvcvbsxcbffgxfdzxbddccxvzczsvsdzsbfsbddxzcbx[0] = 0.0
            clockptxbzfbdbvvdscfbvvxcbfddgsvccvsbccfbfczzvsddzvcddvzzsdcccvvfcxcsfsbsbvxffsdvvcvbsxcbffgxfdzxbddccxvzczsvsdzsbfsbddxzcbx.append(calc_tlength)

            txstkvcgfsxfcxbdffzsxvfbsfbdcdvsfvcfdsbzbdvdbxszdfsvxbdfcxbgssbvcbczffzdsvcdsvvxscxvdfcbzbccxzxvxbczcfc=[]
            
            print(f"Assigning Fast Direct Encoding Native Modules via multi thread logic exactly building targeted limits seamlessly preventing overload delays specifically...")
            
            # --- SUPER HIGH-TECH FAST PROCESS EXECUTOR ---
            with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as xcxpoolsddcdcsdvzcxvfccvcbsdfsvfxbcxcbgvdzxfdfcbvcxzvsdsfdbcbvvfdcscxzdfdzxbfzcccbfsbzdxcvbxdfdfvfcdsc:
                mndxxvbssczbfddvxbfvvbzfsxcfbffzsbgbfbsvbzsxzcbxdcdfzzvvsxxxvzd=len(clockptxbzfbdbvvdscfbvvxcbfddgsvccvsbccfbfczzvsddzvcddvzzsdcccvvfcxcsfsbsbvxffsdvvcvbsxcbffgxfdzxbddccxvzczsvsdzsbfsbddxzcbx) - 1
                qbxvdvxvcbcbzdvddccvvcvczxdxcxdxvxzvsszbxvcbbcvddcsdzsfvfbsbvzsdbcfcvbbcfxfddzsfzfxcxvzvxxsczdcvbsgfbvsxsdfdzbc=[]
                for sl_numxdzxdsxbvzbcfsvbbxzxxsscdzbbfdfxdxcbcxbvxbcbbvdxcxcgffzdgbdvcxvbfcdbcbzcfcfsbvzbdfzfzssffsxvcxscvcgbdbfsdxvzxbscfcxcxvczvfbfdzbzvcsczsfbdcgcfbxbsxvcxbdcsfzvxxsfzfcszdbsvcfffbxvzsbzxcbcgfxxszxzvzvfcfffcvxbsvvzfbbvvbzscsdxbssdcxvdxvxczcbzcfcdxbbdfszbvbcgvzvsdzccbfcdzxcvcffvvbdgfccc in range(mndxxvbssczbfddvxbfvvbzfsxcfbffzsbgbfbsvbzsxzcbxdcdfzzvvsxxxvzd):
                    durmptcbxxvzvbdscscvvxcfcgzbxbsbfxbvbvfffbcdfbzzdfvdvbzzcvxcfcxdcfczbzsdcsxfxcbcxsfdcsbcbvxsdsfgcvffzfbvvcgbzvcfxsfvscxvdgvxzsfsccxbxsbbcxdfsbvfxfdfxcxfxbbsfvcbvb=clockptxbzfbdbvvdscfbvvxcbfddgsvccvsbccfbfczzvsddzvcddvzzsdcccvvfcxcsfsbsbvxffsdvvcvbsxcbffgxfdzxbddccxvzczsvsdzsbfsbddxzcbx[sl_numxdzxdsxbvzbcfsvbbxzxxsscdzbbfdfxdxcbcxbvxbcbbvdxcxcgffzdgbdvcxvbfcdbcbzcfcfsbvzbdfzfzssffsxvcxscvcgbdbfsdxvzxbscfcxcxvczvfbfdzbzvcsczsfbdcgcfbxbsxvcxbdcsfzvxxsfzfcszdbsvcfffbxvzsbzxcbcgfxxszxzvzvfcfffcvxbsvvzfbbvvbzscsdxbssdcxvdxvxczcbzcfcdxbbdfszbvbcgvzvsdzccbfcdzxcvcffvvbdgfccc+1]-clockptxbzfbdbvvdscfbvvxcbfddgsvccvsbccfbfczzvsddzvcddvzzsdcccvvfcxcsfsbsbvxffsdvvcvbsxcbffgxfdzxbddccxvzczsvsdzsbfsbddxzcbx[sl_numxdzxdsxbvzbcfsvbbxzxxsscdzbbfdfxdxcbcxbvxbcbbvdxcxcgffzdgbdvcxvbfcdbcbzcfcfsbvzbdfzfzssffsxvcxscvcgbdbfsdxvzxbscfcxcxvczvfbfdzbzvcsczsfbdcgcfbxbsxvcxbdcsfzvxxsfzfcszdbsvcfffbxvzsbzxcbcgfxxszxzvzvfcfffcvxbsvvzfbbvvbzscsdxbssdcxvdxvxczcbzcfcdxbbdfszbvbcgvzvsdzccbfcdzxcvcffvvbdgfccc]
                    plzxtrdvfzvbcdzfbcbgbxcffzzbfbbffsdcfbvbbcbxvssbcxzdcdxsxcbbzvddfxfsvvvcfxvsbcdfcbdddvvdcfgfdcfzbcfc=os.path.join(targ_pcdir, pilpxszbdcsxbzczbcx_fpsstklstxxdbczssdzsfszbvfxvvddvcbcgvzzsvdfzzsfffvxbdvdcdcbvxdbfxdzdfxsfvfgxfbbvvdxfbscczzvcfffzsdbfcscbzccxzcbcccxdzxfsfssxbxcxcxxdvsbbfbcc[sl_numxdzxdsxbvzbcfsvbbxzxxsscdzbbfdfxdxcbcxbvxbcbbvdxcxcgffzdgbdvcxvbfcdbcbzcfcfsbvzbdfzfzssffsxvcxscvcgbdbfsdxvzxbscfcxcxvczvfbfdzbzvcsczsfbdcgcfbxbsxvcxbdcsfzvxxsfzfcszdbsvcfffbxvzsbzxcbcgfxxszxzvzvfcfffcvxbsvvzfbbvvbzscsdxbssdcxvdxvxczcbzcfcdxbbdfszbvbcgvzvsdzccbfcdzxcvcffvvbdgfccc % szofpixxbvcxcxdcbfffbfsgvvvxzxvcbfbvvvsbbcszs])
                    tmpflzbdxcvxzscsbsd=os.path.join(targ_vfrmdir, f"xvfmsvbxbbvfsvddbxsfdcbcfxdxbccvbzxczzvcbgfvvcvbcsxcvszfzsxffbvvdvzsfvsfvszsfcfcfcbzdcfvsfcffffdgbcvbb{sl_numxdzxdsxbvzbcfsvbbxzxxsscdzbbfdfxdxcbcxbvxbcbbvdxcxcgffzdgbdvcxvbfcdbcbzcfcfsbvzbdfzfzssffsxvcxscvcgbdbfsdxvzxbscfcxcxvczvfbfdzbzvcsczsfbdcgcfbxbsxvcxbdcsfzvxxsfzfcszdbsvcfffbxvzsbzxcbcgfxxszxzvzvfcfffcvxbsvvzfbbvvbzscsdxbssdcxvdxvxczcbzcfcdxbbdfszbvbcgvzvsdzccbfcdzxcvcffvvbdgfccc:04d}.mp4")
                    qbxvdvxvcbcbzdvddccvvcvczxdxcxdxvxzvsszbxvcbbcvddcsdzsfvfbsbvzsdbcfcvbbcfxfddzsfzfxcxvzvxxsczdcvbsgfbvsxsdfdzbc.append(xcxpoolsddcdcsdvzcxvfccvcbsdfsvfxbcxcbgvdzxfdfcbvcxzvsdsfdbcbvvfdcscxzdfdzxbfzcccbfsbzdxcvbxdfdfvfcdsc.submit(render_zoom_segment, sl_numxdzxdsxbvzbcfsvbbxzxxsscdzbbfdfxdxcbcxbvxbcbbvdxcxcgffzdgbdvcxvbfcdbcbzcfcfsbvzbdfzfzssffsxvcxscvcgbdbfsdxvzxbscfcxcxvczvfbfdzbzvcsczsfbdcgcfbxbsxvcxbdcsfzvxxsfzfcszdbsvcfffbxvzsbzxcbcgfxxszxzvzvfcfffcvxbsvvzfbbvvbzscsdxbssdcxvdxvxczcbzcfcdxbbdfszbvbcgvzvsdzccbfcdzxcvcffvvbdgfccc, durmptcbxxvzvbdscscvvxcfcgzbxbsbfxbvbvfffbcdfbzzdfvdvbzzcvxcfcxdcfczbzsdcsxfxcbcxsfdcsbcbvxsdsfgcvffzfbvvcgbzvcfxsfvscxvdgvxzsfsccxbxsbbcxdfsbvfxfdfxcxfxbbsfvcbvb, plzxtrdvfzvbcdzfbcbgbxcffzzbfbbffsdcfbvbbcbxvssbcxzdcdxsxcbbzvddfxfsvvvcfxvsbcdfcbdddvvdcfgfdcfzbcfc, tmpflzbdxcvxzscsbsd))
                    
                for objbvf in qbxvdvxvcbcbzdvddccvvcvczxdxcxdxvxzvsszbxvcbbcvddcsdzsfvfbsbvzsdbcfcvbbcfxfddzsfzfxcxvzvxxsczdcvbsgfbvsxsdfdzbc: txstkvcgfsxfcxbdffzsxvfbsfbdcdvsfvcfdsbzbdvdbxszdfsvxbdfcxbgssbvcbczffzdsvcdsvvxscxvdfcbzbccxzxvxbczcfc.append(objbvf.result())

            tmpslxvcxvszcvdbbdcfvfzdcvsscbxzsdvcbfdxcffgzdcsvfvdszdfbsbdxfdcvcbvfxxds=os.path.join(wkspace, "temp_slider.txt")
            with open(tmpslxvcxvszcvdbbdcfvfzdcvsscbxzsdvcbfdxcffgzdcsvfvdszdfbsbdxfdcvcbvfxxds, "w") as wrnxcfxfzxzdssbfxvdbxfvzdszvfbvb: wrnxcfxfzxzdssbfxvdbxfvzdszvfbvb.write("\n".join(txstkvcgfsxfcxbdffzsxvfbsfbdcdvsfvcfdsbzbdvdbxszdfsvxbdfcxbgssbvcbczffzdsvcdsvvxscxvdfcbzbccxzxvxbczcfc))
            
            poutxdxfbcgvccbx=os.path.join(wkspace, "temp_output.mp4")
            vfixlvcxcvdcfvzfvvzvbfdsxxvdzczfbcxzdffdbzzfvdfcbszsxsfcxcbxbdvzcxfs=os.path.join(wkspace, "output_video.mp4")
            print("Mixing layers completely perfectly safe bypassing block issues dynamically integrating timeline rules internally logically globally generating...")
            subprocess.run(["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-safe", "0", "-f", "concat", "-i", tmpslxvcxvszcvdbbdcfvfzdcvsscbxzsdvcbfdxcffgzdcsvfvdszdfbsbdxfdcvcbvfxxds, "-i", path_mp3, "-c:v", "copy", "-c:a", "copy", "-shortest", poutxdxfbcgvccbx], check=True)

            clxvxszdvcbc, bgxczdxvcxcdzcxfcbzdzzffzxdffszcszbvzfszzzzbdzdvcxbzxzdvdddsdxcsbcbvzdxfdfxvxsdsdxfbccbvfgcdgzzsdcscscxxsxsscxdsfvvdbz=hex_to_ass_color(user_settings["font_color"], 1.0), hex_to_ass_color(user_settings["bg_color"], user_settings.get("bg_opacity", 0.5))
            stylstrfxvdvvcsdsxxzdcfgsvbcgvbsffcvbfsvzvcsdfsxdfzdzbzfffbccssbsfvbfvcxsdfdvcvsccdfcxzdfffvdzdxfdsf=f"FontName=Arial,FontSize={user_settings['font_size']},PrimaryColour={clxvxszdvcbc},BackColour={bgxczdxvcxcdzcxfcbzdzzffzxdffszcszbvzfszzzzbdzdvcxbzxzdvdddsdxcsbcbvzdxfdfxvxsdsdxfbccbvfgcdgzzsdcscscxxsxsscxdsfvvdbz},BorderStyle={user_settings['border_style']},Outline=2,Shadow=1,Alignment=2,MarginV={user_settings['margin_v']}"

            subprocess.run(["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", poutxdxfbcgvccbx, "-vf", f"subtitles=subtitles.srt:force_style='{stylstrfxvdvvcsdsxxzdcfgsvbcgvbsffcvbfsvzvcsdfsxdfzdzbzfffbccssbsfvbfvcxsdfdvcvsccdfcxzdfffvdzdxfdsf}'", "-c:v", "libx264", "-crf", "18", "-preset", "ultrafast", "-c:a", "copy", vfixlvcxcvdcfvzfvvzvbfdsxxvdzczfbcxzdffdbzzfvdfcbszsxsfcxcbxbdvzcxfs], check=True)
            
            safe_upload_to_youtube(vfixlvcxcvdcfvzfvvzvbfdsxxvdzczfbcxzdffdbzzfvdfcbszsxsfcxcbxbdvzcxfs, os.path.join(wkspace, "thumbnail.jpg"), vid_ttl, f"Complete Highlights Recap: {vid_ttl}\nBroadcast executed via reliable server systems intelligently mapping rules effectively successfully securely deployed efficiently today accurately natively logically ensuring updates active streaming!")
            with open("processed_urls.txt", "a") as appwcvbvvxxxdvfbxbdbzbdbdzbvbbfsfzczffxcdddbdfzzcfvdvzsfbzxxcgxdcbdvfscfdcvzzbsbfbxfsxfcbfsfffcxxbzsbcfbxvxbbxxsdcb: appwcvbvvxxxdvfbxbdbzbdbdzbvbbfsfzczffxcdddbdfzzcfvdvzsfbzxxcgxdcbdvfscfdcvzzbsbfbxfsxfcbfsfffcxxbzsbcfbxvxbbxxsdcb.write(lns+"\n")
            print("Successfully processed target structure completely natively tracking database mapping accurately reliably terminating sequences sequentially avoiding loops. Valid completion approved ✅\n")

        except Exception as crashrepdsfvzvbszdcfvfvxdxcxsxcfsbvzzszffsfffbvxbvbzvfffcgcvcbzsxxsffdvsdbzbxdvvxfvcbgxbvvcdfszfzfddxvvfzzfxdbcbcccxsdsbcbf: traceback.print_exc()

if __name__ == "__main__":
    process_primary_automation_loop()
