import glob
import subprocess
import os

mp3_all = glob.glob(os.path.join("./", "*.mp3"))
mp4_all = glob.glob(os.path.join("./", "*.mp4"))

for i in len(mp3_all):
	# end with _FX.mp4
	filename = mp4_all[i][:-7] + "_REP.mp4"
	ffmpeg_command = "ffmpeg -i " + "'" + mp4_all[i] + "'" + " -i " +"'" + mp3_all[i] + "'" + " -map 0:0 -map 1:0 -c:v copy -c:a libmp3lame -q:a 1 -shortest " + \
				"'" + filename + "'" 
	ret1 = subprocess.run(ffmpeg_command, shell=True)
        if ret1.returncode == 0:	
        	print("第 %d 个视频文件 %s 成功替换音频 %s" % (i+1, mp4_all[i], mp3_all[i]))			
    	else:
    		print("第 %d 次运行错误！" % (i+1))
		break

