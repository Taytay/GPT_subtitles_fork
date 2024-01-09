import os
import re
import subprocess
import time
from urllib.parse import parse_qs, urlparse

import pytube
from PIL import Image
from pythumb import Thumbnail
from pytube import YouTube
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import SRTFormatter

# Fixes a "failed to get name" error:
# https://github.com/pytube/pytube/issues/1473
pytube.innertube._default_clients["ANDROID"] = pytube.innertube._default_clients["WEB"]


class TranscriptFetcher:
    def __init__(self, video_id):
        self.video_id = video_id
        self.transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

    def fetch_transcript(self, target_language):
        try:
            transcript = self.transcript_list.find_manually_created_transcript(
                [target_language]
            )
        except:
            try:
                transcript = self.transcript_list.find_manually_created_transcript(
                    self.transcript_list._manually_created_transcripts.keys()
                )
            except:
                try:
                    transcript = self.transcript_list.find_generated_transcript(
                        [target_language]
                    )
                except:
                    transcript = self.transcript_list.find_generated_transcript(
                        self.transcript_list._generated_transcripts.keys()
                    )

        if target_language != "en":
            transcript = transcript.translate(target_language)
        transcript_data = transcript.fetch()
        return transcript_data, transcript.language


class SRTDownloader:
    def __init__(self, url, title, output_path):
        self.url = url
        self.title = title
        self.output_path = output_path

    def get_youtube_id(self):
        parsed_url = urlparse(self.url)

        if parsed_url.netloc == "www.youtube.com":
            return parse_qs(parsed_url.query).get("v", [None])[0]
        raise ValueError(f"Invalid YouTube URL: {self.url}")

    def download(self, target_language):
        try:
            video_id = self.get_youtube_id()
            transcript_data, language = TranscriptFetcher(video_id).fetch_transcript(
                target_language
            )
            srt_formatted = SRTFormatter().format_transcript(transcript_data)

            filename = f"yt_subtitles_[{language}].srt"  # Use the language code in the filename
            srt_file_path = os.path.join(self.output_path, filename)

            with open(srt_file_path, "w", encoding="utf-8") as file:
                file.write(srt_formatted)

            print(f"SRT file downloaded at: {srt_file_path}")
            return True
        except Exception as e:
            print(f"Failed to download transcript. Error: {e}")
            return False


def resize_image(input_path, output_path, new_dimensions):
    with Image.open(input_path) as img:
        resized_img = img.resize(new_dimensions)
        resized_img.save(output_path)


def sanitize_filename(filename):
    # This will replace reserved characters with an underscore
    return re.sub(r'[\/:*?"<>|!]', "_", filename)


class YouTubeDownloader:
    def __init__(self, url, target_language="en"):
        self.url = url
        self.target_language = target_language
        if target_language == "zh":
            self.target_language = "zh-Hans"

    def download_video(self, output_folder:str = ""):
        count = 0
        while True:
            yt = YouTube(self.url)
            if count > 5:
                print("Use unknown_title as the video name")
                title = "unknown_title"
                break
            try:
                title = yt.title
                break
            except:
                print("Failed to get name. Retrying... Press Ctrl+Z to exit")
                count += 1
                time.sleep(1)
                continue

        title = sanitize_filename(title)
        print("Downloading video: " + title)

        # By default, we download to videos/title
        # but the user might suggest something else
        
        if output_folder == None or output_folder == "":
            output_folder = os.path.join("/content/videos")
        else:
            # normalize the output_folder path - if it's something like "..", we need a real absolute path: 
            output_folder = os.path.abspath(output_folder)

        video_folder = os.path.join(output_folder, title)

        # create the video folder, including parents
        os.makedirs(video_folder, exist_ok=True)

        output_filename = os.path.join(video_folder, f"video.%(ext)s")
        final_output_filename = os.path.join(video_folder, f"video.mp4")
        # Does the file already exist?
        if os.path.exists(final_output_filename):
            print(f"File already exists. Won't download. {final_output_filename}")
            return final_output_filename

        # Download English transcript first
        SRTDownloader(self.url, title, video_folder).download("en")
        # Then try downloading the target language transcript
        if self.target_language != "en":
            SRTDownloader(self.url, title, video_folder).download(self.target_language)

        # Download the thumbnail using pythumb
        thumbnail = Thumbnail(self.url)
        thumbnail.fetch()
        thumbnail.save(dir=video_folder, filename="thumbnail", overwrite=True)

        # Resize the thumbnail and save as a new file
        thumbnail_path = os.path.join(video_folder, "thumbnail.jpg")
        resized_thumbnail_path = os.path.join(video_folder, "thumbnail_resized.jpg")

        with Image.open(thumbnail_path) as img:
            resized_img = img.resize((1152, 720))
            resized_img.save(
                resized_thumbnail_path
            )  # save the resized image as a new file

        print(f"Original thumbnail saved at: {thumbnail_path}")
        print(f"Resized thumbnail saved at: {resized_thumbnail_path}")

        # Download the video using yt-dlp
        youtube_dl_command = f"yt-dlp -f 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]' --merge-output-format mp4 -o \"{output_filename}\" {self.url}"
        subprocess.run(youtube_dl_command, shell=True, check=True)

        # Find the downloaded video file
        downloaded_video_path = None
        count_time = 0
        while downloaded_video_path is None:
            # check if the video has been downloaded
            # look in the output folder to detrmine if there is an mp4 file there:
            # for file in os.listdir(video_folder):
            #     if file.endswith(".mp4") and not file.endswith("temp.mp4") and not file.endswith("tmp.mp4"):
            #         downloaded_video_path = os.path.join(video_folder, file)
            #         break
            # 
            if os.path.exists(final_output_filename):
                downloaded_video_path = final_output_filename
                break
            print(
                f" | Waiting for video.mp4 to be downloaded... | time elapsed: {count_time} seconds |"
            )
            count_time += 5
            # Sleep 5 sec:
            time.sleep(5)

        print("Download complete: " + downloaded_video_path)
        print(f"File size: {os.path.getsize(downloaded_video_path) / 1e6} mb")

        return downloaded_video_path
