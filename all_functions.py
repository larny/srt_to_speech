import pysrt
import pyperclip
# import opencc
import subprocess
import re
import datetime
import tqdm
import jieba
import os
import time
import glob
import zipfile
from pydub import AudioSegment

def get_fx_mp4(raw_mp4, ass_file, extra_name='FX'):
    output_mp4 = raw_mp4.replace('.mp4', '_' + extra_name + '.mp4')
    cmd = "ffmpeg -hwaccel cuda -c:v h264_cuvid -i " + raw_mp4 + " -vf subtitles=" + ass_file + " -c:v h264_nvenc -b:v 15M -c:a copy " + output_mp4 + " -y"
    # ffpb.main(argv=None, stream=sys.stderr, encoding=None, tqdm=tqdm)
    pyperclip.copy(cmd)
    # print("已复制结果到剪贴板")
    return cmd

def num2chinese(num):
    chinese_nums = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九']
    if num < 0 or num > 10:
        return '不支持转换该数字'
    return chinese_nums[num]

def rename_mp4(prefix, episode):
    # 获取目录下的所有 MP4 文件
    mp4_files = [f for f in os.listdir(prefix) if f.endswith(".mp4")]
    srt_files = [f for f in os.listdir(prefix) if f.endswith(".srt")]


    # 检查是否找到了 MP4 文件
    if mp4_files:
        # 取第一个 MP4 文件进行重命名
        src = os.path.join(prefix, mp4_files[0])
        dst = os.path.join(prefix, f"{episode}.mp4")
        os.rename(src, dst)
        print(f"Renamed '{src}' to '{dst}'")
    else:
        print("No MP4 file found in the given directory.")
        
    if srt_files:
        src = os.path.join(prefix, srt_files[0])
        dst = os.path.join(prefix, f"{episode}.srt")
        os.rename(src, dst)
        print(f"Renamed '{src}' to '{dst}'")
    else:
        print("No SRT file found in the given directory.")

# STEP1.2 -- 对讯飞生成的srt字幕，进行合并、替换词汇、去除语气词操作
def process_subtitle(input_srt, output_srt, span, max_chars, max_seconds, dict_file, mood_file):

    def merge_subtitles(subs, span, max_chars=30, max_seconds=20):
        def count_chinese_chars(text):
            return sum(1 for char in text if '\u4e00' <= char <= '\u9fff')
        
        print(f"合并前的字幕总行数: {len(subs)}")
        i = 0
        while i < len(subs) - 1:
            a = subs[i]
            b = subs[i + 1]

            # 将 SubRipTime 对象转换为 timedelta 对象
            a_end = datetime.timedelta(hours=a.end.hours, minutes=a.end.minutes, seconds=a.end.seconds, microseconds=a.end.milliseconds * 1000)
            a_start = datetime.timedelta(hours=a.start.hours, minutes=a.start.minutes, seconds=a.start.seconds, microseconds=a.start.milliseconds * 1000)
            b_start = datetime.timedelta(hours=b.start.hours, minutes=b.start.minutes, seconds=b.start.seconds, microseconds=b.start.milliseconds * 1000)
            b_end = datetime.timedelta(hours=b.end.hours, minutes=b.end.minutes, seconds=b.end.seconds, microseconds=b.end.milliseconds * 1000)

            # 计算间隔
            gap = (b_start - a_end).total_seconds()

            if gap < span:
                # 合并字幕的条件
                merged_text = a.text + " " + b.text
                a_duration = (a_end - a_start).total_seconds()
                b_duration = (b_end - b_start).total_seconds()
                merged_duration = a_duration + b_duration

                if count_chinese_chars(merged_text) <= max_chars and merged_duration <= max_seconds:
                    a.text = merged_text
                    a.end = b.end
                    subs.remove(b)
                else:
                    i += 1
            else:
                i += 1
        print(f"合并后的字幕总行数: {len(subs)}")
        return subs

    def remove_mood_words(subs, mood_file):
        with open(mood_file, 'r', encoding='utf-8') as f:
            mood_words = [line.strip() for line in f.readlines()]

        for sub in subs:
            for mood_word in mood_words:
                sub.text = sub.text.replace(mood_word, '')

    def remove_mood_words_smart(subs, mood_file):
        with open(mood_file, "r", encoding="utf-8") as file:
            mood_words = [line.strip() for line in file]
        mood_word_pattern = r'\b({})\b'.format('|'.join(mood_words))

        for sub in subs:
            # 使用jieba分词
            words = list(jieba.cut(sub.text))
            
            # 移除语气词和短语
            cleaned_words = []
            i = 0
            while i < len(words):
                word = words[i]
                if i < len(words) - 1 and (word + words[i + 1]) in mood_words:
                    i += 2
                elif not re.match(mood_word_pattern, word):
                    cleaned_words.append(word)
                    i += 1
                else:
                    i += 1

            # 重新组合成句子
            sub.text = ''.join(cleaned_words)
        return subs

    def replace_words(subs, dict_file):
        with open(dict_file, 'r', encoding='utf-8') as f:
            replacement_rules = [line.strip().split('--') for line in f.readlines()]

        for i, sub in enumerate(subs):
            for s1, s2 in replacement_rules:
                if s1 in sub.text:
                    # print(f"Replacing '{s1}' with '{s2}' in subtitle {i+1}")
                    sub.text = sub.text.replace(s1, s2)
        return subs

    # 读取字幕文件
    subs = pysrt.open(input_srt, encoding='utf-8')

    # 任务1
    subs = merge_subtitles(subs, span, max_chars, max_seconds)

    # 任务2
    # remove_mood_words(subs, mood_file)
    # 任务2 智能分词方法
    subs = remove_mood_words_smart(subs, mood_file)

    # 任务3
    subs = replace_words(subs, dict_file)

    # 保存修改后的字幕
    subs.save(output_srt, encoding='utf-8')

# STEP2 -- 先在_CHS.ass里校对中文，ass to srt, 创建新的空文件(_GPT.txt)
def create_empty_file(path):
    output_name = path + '_GPT.txt'
    try:
        with open(output_name, 'x', encoding='utf-8') as f:
            pass
    except FileExistsError:
        print(f"File {output_name} already exists. Do you want to overwrite it? (y/n)")
        choice = input().lower()
        if choice == "y":
            with open(output_name, 'w', encoding='utf-8') as f:
                pass
        else:
            print("File not written.")
    current_time = datetime.datetime.now()
    print("Function create_empty_file executed at:", current_time)

def contat_lists(list1, list2):
    new_list = []
    for i in range(len(list1)):
        start_time, end_time  = list1[i]
        new_list.append(start_time + ';' + end_time + ';' + list2[i])
    return new_list

def build_all_lists(raw_text):
    spt1 = raw_text.split('Dialogue: 0,')
    timecode_list = []
    words_list = []
    for item in spt1[1:]:
        spt2 = item.split(',')
        words_start = item.rfind(',,')
        words_ = item[words_start + 2: -1]
        timecode_list.append(spt2[:2])
        words_list.append(words_.title())
    all_list = contat_lists(timecode_list, words_list)
    return all_list

def build_output_srt(all_list_):
    str1 = ''
    for i in range(len(all_list_)):
        str1 += str(i+1) + '\n'
        start_time, end_time, words = all_list_[i].split(';')
        str1 += '0' + start_time + '0' +  ' --> ' + '0' + end_time + '0' + '\n' + words.rstrip().lstrip() + '\n' + '\n'
    return str1  

def ass_to_srt(filename, my_dict, my_dict2, extra_name=''):
    file1 = open(filename, 'r', encoding='utf-8')
    all_texts= file1.read()
    all_lists = build_all_lists(all_texts)
    output_ = build_output_srt(all_lists)
    new_output = output_.replace("{\i1}", "<i><b>")
    new_output = new_output.replace("{\i0}", "</i></b>")
    new_output = new_output.replace("C4D", "Cinema 4D ")
    new_output = new_output.replace("Ctrl", "Control")
    res = re.findall(r"<i><b>.*?</i></b>", new_output)
    for i in res:
        new_output = new_output.replace(i, i[0:6] +i[6:-8].title() + i[-8:])

    res2 = re.findall(r"{\\b1}.*?{\\b0}", new_output)
    for i in res2:
        new_output = new_output.replace(i, i[0:5] +i[5:-5].upper() + i[-5:])

    # 匹配中文+大写字母，在其中间增加空格
    res3 = re.findall(r"[\u4e00-\u9fa5][A-Z]", new_output)
    for i in res3:
        new_output = new_output.replace(i, i[0] + ' ' + i[-1])

    # 匹配单词结尾的小写英文，在其结尾增加空格
    res4 = re.findall(r"[a-z][\u4e00-\u9fa5]", new_output)
    for i in res4:
        new_output = new_output.replace(i, i[0] + ' ' + i[-1])

    new_output = new_output.replace("{\\b1}", "<i><b>")
    new_output = new_output.replace("{\\b0}", "</i></b>")
    new_output = new_output.replace("{\\u1}", "<i><b>")
    new_output = new_output.replace("{\\u0}", "</i></b>")
    new_output = new_output.replace(".", ",")
    new_output = new_output.replace("  ", " ")

    for j in my_dict:
        new_output = new_output.replace(j.title(), j.upper())
    
    for k in my_dict2:
        new_output = new_output.replace(k.title(), k)

    output_name = str(filename)[:-4] + extra_name + '.srt'
    try:
        with open(output_name, 'x', encoding='utf-8') as f:
            f.write(new_output)
    except FileExistsError:
        print(f"File {output_name} already exists. Do you want to overwrite it? (y/n)")
        choice = input().lower()
        if choice == "y":
            with open(output_name, 'w', encoding='utf-8') as f:
                f.write(new_output)
        else:
            print("File not written.")
    current_time = datetime.datetime.now()
    print("Function ass_to_srt executed at:", current_time)
        
# STEP2.2 -- 得到压制特效字幕的代码，自动压制
def execute_command(prefix, cmd):
    os.chdir(prefix)
    process = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True
    )

    duration_regex = re.compile(r"Duration: (\d{2}):(\d{2}):(\d{2})\.\d{2}")
    frame_regex = re.compile(r"frame=\s*(\d+)")
    speed_regex = re.compile(r"speed=\s*(\d+\.\d+x)")

    total_frames = 0
    current_frame = 0
    progress_bar = None

    start_time = time.time()

    while process.poll() is None:
        output = process.stderr.readline().strip()
        
        if output:
            duration_match = duration_regex.search(output)
            frame_match = frame_regex.search(output)
            speed_match = speed_regex.search(output)

            if duration_match:
                hours, minutes, seconds = map(int, duration_match.groups())
                total_frames = 30 * (hours * 3600 + minutes * 60 + seconds)
                progress_bar = tqdm.tqdm(total=total_frames, unit="frame", leave=False)

            if frame_match and progress_bar is not None:
                new_frame = int(frame_match.group(1))
                progress_bar.update(new_frame - current_frame)
                current_frame = new_frame

            if speed_match and progress_bar is not None:
                speed = speed_match.group(1)
                progress_bar.set_postfix_str(f"speed: {speed}")

    if progress_bar:
        progress_bar.close()

    end_time = time.time()
    total_duration = end_time - start_time
    print(f"Total time taken for compression: {total_duration:.2f} seconds")

    return process.returncode

def srt_to_txt(filename, mark = ""):
    raw_txt = ''
    srt1 = pysrt.open(filename)
    txt_name = filename.replace('srt', 'txt')
    for i in range(len((srt1))):
        if srt1[i].text[-1] == mark:
            raw_txt += srt1[i].text + '\n'
        else:
            raw_txt += srt1[i].text + mark + '\n'
    try:
        with open(txt_name, 'x', encoding='utf-8') as f:
            f.write(raw_txt)
    except FileExistsError:
        print(f"File {txt_name} already exists. Do you want to overwrite it? (y/n)")
        choice = input().lower()
        if choice == "y":
            with open(txt_name, 'w', encoding='utf-8') as f:
                f.write(raw_txt)
        else:
            print("File not written.")            
    current_time = datetime.datetime.now()
    print("Function srt_to_txt executed at:", current_time)

# STEP3 -- 以srt时间为基准，替换字典中的短语，将_GPT.txt转换_GPT_MOD.srt，
def replace_words(s, dictionary):
    def replace_match(match):
        word = match.group(0)
        return dictionary.get(word, word) if dictionary.get(word) != "" else word.title()

    pattern = re.compile("|".join(re.escape(key) for key in dictionary.keys()))
    return pattern.sub(replace_match, s)
def get_replace_dict(dict):
    replace_dict = {}
    with open(dict, "r") as f:
        for line in f:
            parts = line.strip().split("--")
            if len(parts) == 2:
                key, value = parts
                replace_dict[key.strip()] = value.strip()
            elif len(parts) == 1:
                key = parts[0].strip()
                replace_dict[key] = ""
    return replace_dict
replace_dict = get_replace_dict(r'D:\Users\Larny\srt_to_speech\replace_dict.txt')


def replace_period(s1):
    # 使用正则表达式查找所有符合'. '[句号+空格]之后跟着一个大写字母的情况，并分组
    pattern = re.compile(r'\. (\w)')

    def to_lower(match):
        # 对每一组匹配项进行处理，如果是 'I' 则不变，其它情况转为小写
        return ', ' + match.group(1) if match.group(1) == 'I' else ', ' + match.group(1).lower()

    # 用处理过的匹配项替换原匹配项
    s1 = pattern.sub(to_lower, s1)

    # 将句中的大写字母转化为小写，保留句尾的大写字母
    s1 = s1[:-1] + s1[-1].upper() if s1[-1].islower() else s1

    return s1

def txt_to_srt_withref(txt_file, srt_file, extra_name='', dict = replace_dict):
    srt1 = pysrt.open(srt_file)
    srt_txt = open(srt_file, encoding='utf-8').readlines()
    txt1 = open(txt_file, encoding='utf-8').readlines()
    start_idx = 2
    count_ = 0
    raw_txt = ''
    for i in range(len((srt_txt))):
        rep_period_txt = replace_period(txt1[count_])
        if i == start_idx:
            # print(start_idx, count_)
            # new_txt = replace_words(txt1[count_], dict)
            new_txt = replace_words(rep_period_txt, dict) 
            start_idx += 4
            if count_ < len(txt1) and txt1[count_-1].strip()[-1] == ',':
                new_txt = new_txt[0].lower() + new_txt[1:]            
            count_ += 1
            raw_txt += new_txt
        else:
            raw_txt += srt_txt[i]

    with open(txt_file[:-4] + '_' + extra_name + '.srt', mode='w') as f1:
        f1.write(raw_txt)
    current_time = datetime.datetime.now()
    print("Function txt_to_srt_withref executed at:", current_time)
    return

def sync_subtitles(chinese_srt, english_srt):
    # 加载中英文字幕文件
    chinese_subs = pysrt.open(chinese_srt, encoding='utf-8')
    english_subs = pysrt.open(english_srt, encoding='utf-8')

    # 确保中英文字幕的数量相同
    if len(chinese_subs) != len(english_subs):
        raise ValueError("字幕数量不匹配，请检查输入的字幕文件。")

    # 将中文字幕的时间轴同步到英文字幕的时间轴
    for i in range(len(chinese_subs)):
        chinese_subs[i].start = english_subs[i].start
        chinese_subs[i].end = english_subs[i].end
    chinese_subs.save(chinese_srt, encoding='utf-8')
    current_time = datetime.datetime.now()
    print("Function sync_subtitles executed at:", current_time)

# STEP5.1 -- 自动合并MP3文件
def merge_audio_files(folder_path):
    # 解压缩Clips开头的压缩包
    zip_files = glob.glob(os.path.join(folder_path, 'Clips*.zip'))
    for zip_file in zip_files:
        with zipfile.ZipFile(zip_file, 'r') as zf:
            zf.extractall(folder_path)
            
    # 寻找以 "Clips" 开头的子文件夹
    clips_folders = [os.path.join(folder_path, d) for d in os.listdir(folder_path) if d.startswith("Clips") and os.path.isdir(os.path.join(folder_path, d))]

    # 初始化音频片段列表
    audio_segments = []

    # 遍历所有的 "Clips" 文件夹
    for clips_folder in clips_folders:
        # 获取文件夹中以 "KM" 开头的 MP3 文件
        km_files = sorted([f for f in os.listdir(clips_folder) if f.startswith("KM") and f.endswith(".mp3")])

        # 遍历每个 MP3 文件并将其添加到音频片段列表中
        for km_file in km_files:
            audio_file_path = os.path.join(clips_folder, km_file)
            audio = AudioSegment.from_mp3(audio_file_path)
            audio_segments.append(audio)

    # 使用 `crossfade()` 方法合并音频片段
    crossfade_duration = 0  # 设置交叉淡入淡出的持续时间（以毫秒为单位）
    merged_audio = audio_segments[0]
    for segment in audio_segments[1:]:
        merged_audio = merged_audio.append(segment, crossfade=crossfade_duration)

    # 将合并后的音频文件保存到指定的文件夹中
    output_file_path = os.path.join(folder_path, "KM-1.mp3")
    merged_audio.export(output_file_path, format="mp3", bitrate="192k")
    current_time = datetime.datetime.now()
    print("Function sync_subtitles executed at:", current_time)
def merge_wav_files(folder_path):
    # 解压缩Clips开头的压缩包
    zip_files = glob.glob(os.path.join(folder_path, 'Clips*.zip'))
    for zip_file in zip_files:
        with zipfile.ZipFile(zip_file, 'r') as zf:
            zf.extractall(folder_path)

    # 合并KM开头的wav文件
    wav_files = glob.glob(os.path.join(folder_path, 'Clips*/KM-*.wav'))
    wav_files.sort()

    combined_audio = AudioSegment.empty()
    for wav_file in wav_files:
        audio = AudioSegment.from_wav(wav_file)
        combined_audio += audio

    # 保存合并后的文件为KM-1.wav
    output_file = os.path.join(folder_path, 'KM-1.wav')
    combined_audio.export(output_file, format="wav")
    # 保存合并后的文件为KM-1.mp3，比特率为192k
    output_mp3_file = os.path.join(folder_path, 'KM-1.mp3')
    combined_audio.export(output_mp3_file, format="mp3", bitrate="192k")

#　---------　先在MOD.srt 中更改结尾时间使时间连续（前300ms，后50ms），尽量留空间 -------------
def pysrttime_to_milliseconds(t):
    return ((t.hours * 60 + t.minutes) * 60 + t.seconds)*1000 + t.milliseconds

def generate_correted_wav(dub_mp3, srt_perfect_ENG_name, srt_CHS_name, output_wav, audio_format='mp3'):
    song = AudioSegment.from_mp3(dub_mp3)
    # 获取原始比特率
    bitrate = song.frame_rate
    srt_perfect_ENG = pysrt.open(srt_perfect_ENG_name)
    srt_CHS = pysrt.open(srt_CHS_name)

    pdbar = tqdm.tqdm(total=len(srt_perfect_ENG), desc="Generating audio")

    outwav = AudioSegment.empty()
    outwav += AudioSegment.silent(duration = pysrttime_to_milliseconds(srt_CHS[0].start))

    extra_length = 0
    for i in range(len((srt_perfect_ENG))):
        j = srt_perfect_ENG[i]
        k = srt_CHS[i]
        # 中文字幕的下一行
        k_next = srt_CHS[i+1] if i != len((srt_perfect_ENG)) - 1 else k
        k_next_start = pysrttime_to_milliseconds(k_next.start)
        start1 = pysrttime_to_milliseconds(j.start)
        end1 = pysrttime_to_milliseconds(j.end)
        # 英文配音长度
        duration1 = pysrttime_to_milliseconds(j.duration)
        # 中文字幕长度
        duration2 = pysrttime_to_milliseconds(k.duration) - extra_length

        # +英文配音
        outwav += song[start1: end1]
        
        # + 英文配音时间小于中文字幕
        if duration1 < duration2:
            margin = k_next_start - pysrttime_to_milliseconds(k.start) - duration1  - extra_length
            if margin > 0:
                outwav += AudioSegment.silent(duration = margin)
                extra_length = 0
        else:
            # 说明连续几句都是英文配音时间大于中文字幕
            if extra_length != 0:
                extra_length += duration1 + pysrttime_to_milliseconds(k.start) - k_next_start
            else:
                extra_length = duration1 + pysrttime_to_milliseconds(k.start) - k_next_start
            # margin2 = pysrttime_to_milliseconds(k_next.start) - pysrttime_to_milliseconds(k.start) - duration1 - extra_length
            # if margin2 > 0:
            #     outwav += AudioSegment.silent(duration = margin2)

        pdbar.update()
    pdbar.close()
    outwav.export(output_wav, format=audio_format, bitrate=f"{bitrate}k")
    print("mp3 saved as %s" % (output_wav))
    current_time = datetime.datetime.now()
    print("Function generate_correted_wav executed at:", current_time)

    return 

def generate_correted_wav2(dub_wav, srt_perfect_ENG_name, srt_CHS_name, output_wav):
    song = AudioSegment.from_wav(dub_wav)
    # 获取原始比特率
    bitrate = song.frame_rate
    srt_perfect_ENG = pysrt.open(srt_perfect_ENG_name)
    srt_CHS = pysrt.open(srt_CHS_name)

    pdbar = tqdm.tqdm(total=len(srt_perfect_ENG), desc="Generating audio")

    outwav = AudioSegment.empty()
    outwav += AudioSegment.silent(duration = pysrttime_to_milliseconds(srt_CHS[0].start))

    extra_length = 0
    for i in range(len((srt_perfect_ENG))):
        j = srt_perfect_ENG[i]
        k = srt_CHS[i]
        # 中文字幕的下一行
        k_next = srt_CHS[i+1] if i != len((srt_perfect_ENG)) - 1 else k
        k_next_start = pysrttime_to_milliseconds(k_next.start)
        start1 = pysrttime_to_milliseconds(j.start)
        end1 = pysrttime_to_milliseconds(j.end)
        # 英文配音长度
        duration1 = pysrttime_to_milliseconds(j.duration)
        # 中文字幕长度
        duration2 = pysrttime_to_milliseconds(k.duration) - extra_length

        # +英文配音
        outwav += song[start1: end1]
        
        # + 英文配音时间小于中文字幕
        if duration1 < duration2:
            margin = k_next_start - pysrttime_to_milliseconds(k.start) - duration1  - extra_length
            if margin > 0:
                outwav += AudioSegment.silent(duration = margin)
                extra_length = 0
        else:
            # 说明连续几句都是英文配音时间大于中文字幕
            if extra_length != 0:
                extra_length += duration1 + pysrttime_to_milliseconds(k.start) - k_next_start
            else:
                extra_length = duration1 + pysrttime_to_milliseconds(k.start) - k_next_start
            # margin2 = pysrttime_to_milliseconds(k_next.start) - pysrttime_to_milliseconds(k.start) - duration1 - extra_length
            # if margin2 > 0:
            #     outwav += AudioSegment.silent(duration = margin2)

        pdbar.update()
    pdbar.close()
    outwav.export(output_wav + ".wav", format="wav")
    print("wav saved as %s.wav" % (output_wav))
    outwav.export(output_wav  + ".mp3", format="mp3", bitrate="192k")
    print("mp3 saved as %s.mp3" % (output_wav))

    current_time = datetime.datetime.now()
    print("Function generate_correted_wav2 executed at:", current_time)

def replace_audio(FX_mp4, correted_wav, output_mp4):
    cmd2 = 'ffmpeg -i ' + FX_mp4 + ' -i ' + correted_wav + ' -filter_complex "[1:a]apad[a]" -map 0:v -map "[a]" -c:v copy -c:a libmp3lame -q:a 1 -shortest ' + output_mp4 + " -y"
    cmd = "ffmpeg -i " + FX_mp4 + " -i " + correted_wav + " -map 0:0 -map 1:0 -c:v copy -c:a libmp3lame -q:a 1 -shortest " + output_mp4 + " -y"
    # print(cmd)
    # 执行cmd命令，如果成功，返回(0, 'xxx')；如果失败，返回(1, 'xxx')
    ret1 = subprocess.run(cmd2, timeout=100, shell=True)
    if ret1.returncode == 0:
        print("Conversion Completed")
    else:
        print("Conversion Error")
    current_time = datetime.datetime.now()
    print("Function replace_audio executed at:", current_time)

def clean_subtitles(file_path):
    subs = pysrt.open(file_path)
    # 遍历字幕并进行清理
    for sub in subs:
        if len(sub.text) > 1 and not sub.text[-2].isalnum() and not sub.text[-1].isalnum():
            sub.text = sub.text[:-1]
        sub.text = sub.text.replace(' ', '，')
        sub.text += '。'
    subs.save(file_path, encoding='utf-8')
    # 获取当前时间并输出
    current_time = datetime.datetime.now()
    print("Function clean_subtitles executed at:", current_time)

def replace_comma_with_period(file_path):
    subs = pysrt.open(file_path)
    for sub in subs:
        sub.text = sub.text.replace(',', '.')
    subs.save(file_path, encoding='utf-8')
    current_time = datetime.datetime.now()
    print("Function replace_comma_with_period executed at:", current_time)

def convert_simplified_to_traditional(input_file):
    converter = opencc.OpenCC('s2t')
    output_file = input_file.replace('_CHS', '_TC')
    
    with open(input_file, 'r', encoding='utf-8') as infile:
        with open(output_file, 'w', encoding='utf-8') as outfile:
            for line in infile:
                outfile.write(converter.convert(line))
    current_time = datetime.datetime.now()
    print("Function convert_simplified_to_traditional executed at:", current_time)

def process_ass_file_old(ass_path, color='red', comment='T'):
    with open(ass_path, 'r', encoding='utf-8-sig') as f:
        content = f.read()

    dialogue_pattern = re.compile(r"Dialogue:\s+\d+,\s*(\d+:\d+:\d+)(?:\.\d+)?,\s*(\d+:\d+:\d+)(?:\.\d+)?,\s*DEL")
    matches = dialogue_pattern.findall(content)

    for match in matches:
        start, end = match
        print(f"{start} {end} {color} {comment}")
    current_time = datetime.datetime.now()
    print("Function ass_to_srt executed at:", current_time)


def process_ass_file(ass_path, color='red', comment='T'):
    with open(ass_path, 'r', encoding='utf-8-sig') as f:
        content = f.readlines()

    dialogue_pattern = re.compile(r"Dialogue:\s+\d+,\s*(\d+:\d+:\d+)(?:\.\d+)?,\s*(\d+:\d+:\d+)(?:\.\d+)?,\s*DEL")

    start, end = None, None
    for line in content:
        match = dialogue_pattern.search(line)
        if match:
            if not start:
                start = match.group(1)
            end = match.group(2)
        else:
            if start and end:
                print(f"{start} {end} {color} {comment}")
                start, end = None, None

    # 如果文件的最后一部分是"DEL"样式，需要再次打印
    if start and end:
        print(f"{start} {end} {color} {comment}")
        
    current_time = datetime.datetime.now()
    print("Function ass_to_srt executed at:", current_time)


def find_gaps_in_subs(srt_path, span, color):
    # 读取SRT文件
    subs = pysrt.open(srt_path)

    # 创建一个空列表，用于存储满足条件的字幕结束时间
    mark_list = []

    # 遍历字幕，检查相邻字幕之间的间隔
    for i in range(len(subs) - 1):
        end_time = subs[i].end.to_time()
        next_start_time = subs[i + 1].start.to_time()
        
        end_datetime = datetime.datetime.combine(datetime.date.min, end_time)
        next_start_datetime = datetime.datetime.combine(datetime.date.min, next_start_time)
        
        gap = (next_start_datetime - end_datetime).total_seconds()

        # 如果间隔大于span，则将当前字幕的结束时间添加到mark_list
        if gap > span:
            mark_list.append(subs[i].end)

    # 将mark_list中的时间转换为字符串并添加到输出字符串中
    output = ""
    for mark in mark_list:
        output += f"{mark.hours:02d}:{mark.minutes:02d}:{mark.seconds:02d} {color}\n"

    # 复制结果到剪贴板
    pyperclip.copy(output)
    print("已复制结果到剪贴板，共%s行" % (len(mark_list)))

def shift_srt_file(input_file, output_file, offset_start_ms, offset_end_ms):
    subtitles = pysrt.open(input_file)
    offset_start = pysrt.SubRipTime(milliseconds=offset_start_ms)
    offset_end = pysrt.SubRipTime(milliseconds=offset_end_ms)

    for i in range(len(subtitles)):
        if i > 0:
            max_start_time = subtitles[i - 1].end
            new_start_time = subtitles[i].start - offset_start
            subtitles[i].start = max(new_start_time, max_start_time)
        else:
            subtitles[i].start -= offset_start
        
        if i < len(subtitles) - 1:
            min_end_time = subtitles[i + 1].start
            new_end_time = subtitles[i].end + offset_end
            subtitles[i].end = min(new_end_time, min_end_time)
        else:
            subtitles[i].end += offset_end

    subtitles.save(output_file)

def modify_srt_from_descript(srt_Descript_name, srt_raw_ENG_name):
    srt_Descript = pysrt.open(srt_Descript_name)
    srt_raw_ENG= pysrt.open(srt_raw_ENG_name)
    src_index = 0
    new_srt = ''
    for i in range(len((srt_raw_ENG))):
        j = srt_Descript[i+src_index]
        j_next = srt_Descript[i+src_index+1] if i != len((srt_raw_ENG))-1 else srt_Descript[i+src_index]
        k = srt_raw_ENG[i]
        text_D = j.text
        text_raw = k.text
        if text_D.strip()[:-2] == text_raw.strip()[:-2]:
            new_srt += str(i+1) + "\n" + str(j.start) + " --> " + str(j.end) + "\n" + text_D + "\n\n"
        else:
            new_srt += str(i+1) + "\n" + str(j.start) + " --> " + str(j_next.end) + "\n" + text_raw + "\n\n"
            src_index += 1
            # 再检测一次
            # if j_next.text.strip()[:-2] == srt_raw_ENG[i+1].text.strip()[:-2]:
            #     new_srt += str(i+1) + "\n" + str(j.start) + " --> " + str(j.end) + "\n" + text_D + "\n\n"
            #     src_index += 1
                # print("asdasd", i, src_index, i-src_index)
                # print(text_D, j.start, j.end)
        print(i+1, i+1+src_index)

    with open(srt_Descript_name.replace('_DES.srt', '') + "_REV.srt", encoding='utf-8', mode='w') as f1:
        f1.write(new_srt)

def mod_to_wellsaid(filename):
    f1 = open(filename).readlines()
    new_txt = ''
    for i in f1:
        if i.strip()[-1] == '.':
            new_txt += i
        elif i.strip()[-1] == ',':
            new_txt += i.strip()[:-1] + '.\n'
        else:
            new_txt += i.strip() + '.\n'
    with open(filename.replace('MOD', 'WSD'), mode='w') as f2:
        f2.write(new_txt)

