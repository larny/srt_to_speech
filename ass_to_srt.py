import glob
import os
import re

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

def output_srt(filename, extra_name=''):
    file1 = open(filename, 'r', encoding='utf-8')
    all_texts= file1.read()
    all_lists = build_all_lists(all_texts)
    output_ = build_output_srt(all_lists)
    new_output = output_.replace("{\i1}", "<i><b>")
    new_output = new_output.replace("{\i0}", "</i></b>")
    new_output = new_output.replace("C4D", "Cinema 4D ")


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

    # 自建库词典，强制变成全大写
    my_dict = ['PBR', 'HDR', 'UV']
    for j in my_dict:
        new_output = new_output.replace(j.title(), j.upper())


    output_name = str(filename)[:-4] + extra_name + '.srt'
    with open(output_name,'w', encoding='utf-8') as f:
        f.write(new_output)

def main():
    ass_all = glob.glob(os.path.join("./", "*.ass"))
    # file1 = open(filename, 'r', encoding='utf-8')
    for i in range(len(ass_all)):
        if 'FX' not in ass_all[i]:
            output_srt(ass_all[i])
    
# s, ori_text, ori_title
if __name__ == '__main__':
    main()