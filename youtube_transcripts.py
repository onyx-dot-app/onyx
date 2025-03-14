#!/usr/bin/env python3
import html
import os
import re
import xml.etree.ElementTree as ET

from pytube import YouTube


def extract_video_id(url):
    """Extract the video ID from a YouTube URL."""
    # Regular expression to match YouTube video IDs
    pattern = r"(?:youtube\.com\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]+)"
    match = re.search(pattern, url)
    if match:
        return match.group(1)
    return None


def get_transcript(video_id, output_dir="transcripts"):
    """Fetch transcript for a YouTube video and save it to a file."""
    try:
        # Create YouTube object
        url = f"https://www.youtube.com/watch?v={video_id}"
        yt = YouTube(url)

        # Get the captions
        caption_tracks = yt.captions

        if not caption_tracks:
            print(f"No captions available for video {video_id}")
            return None

        # Try to get English captions first
        caption = None
        for track in caption_tracks.keys():
            if "en" in track.lower():
                caption = caption_tracks[track]
                break

        # If no English captions, use the first available
        if caption is None and caption_tracks:
            caption = list(caption_tracks.values())[0]

        if caption is None:
            print(f"No usable captions found for video {video_id}")
            return None

        # Get the caption XML
        caption_xml = caption.xml_captions

        # Parse the XML
        transcript_data = []
        try:
            root = ET.fromstring(caption_xml)
            for element in root.findall("./text"):
                start = float(element.get("start", 0))
                duration = float(element.get("dur", 0))
                text = html.unescape(element.text or "")
                transcript_data.append(
                    {"start": start, "duration": duration, "text": text}
                )
        except ET.ParseError:
            print(f"Error parsing captions XML for video {video_id}")
            return None

        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)

        # Write transcript to file
        output_file = os.path.join(output_dir, f"{video_id}.txt")
        with open(output_file, "w", encoding="utf-8") as f:
            # Write video title and URL
            f.write(f"Title: {yt.title}\n")
            f.write(f"URL: {url}\n\n")

            # Write full transcript
            full_text = " ".join([item["text"] for item in transcript_data])
            f.write(full_text)

            # Also write timestamped version
            f.write("\n\n--- TIMESTAMPED VERSION ---\n\n")
            for item in transcript_data:
                timestamp = item["start"]
                minutes = int(timestamp // 60)
                seconds = int(timestamp % 60)
                f.write(f"[{minutes:02d}:{seconds:02d}] {item['text']}\n")

        return output_file
    except Exception as e:
        print(f"Error processing video {video_id}: {str(e)}")
        return None


def process_links_from_file(file_path):
    """Process YouTube links from a file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Process links from the file content
        process_links(content)
    except Exception as e:
        print(f"Error reading file {file_path}: {str(e)}")


def process_links(text):
    """Extract and process YouTube links from text."""
    # Find all YouTube URLs in the text
    pattern = r"https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[a-zA-Z0-9_-]+"
    urls = re.findall(pattern, text)

    if not urls:
        print("No YouTube URLs found in the input.")
        return

    print(f"Found {len(urls)} YouTube URLs.")

    successful = 0
    for url in urls:
        video_id = extract_video_id(url)
        if video_id:
            print(f"Processing: {url} (ID: {video_id})")
            output_file = get_transcript(video_id)
            if output_file:
                print(f"Transcript saved to: {output_file}")
                successful += 1
        else:
            print(f"Could not extract video ID from URL: {url}")

    print(f"\nSummary: Successfully processed {successful} out of {len(urls)} videos.")


if __name__ == "__main__":
    # Create a string with the YouTube links
    youtube_links = """@https://www.youtube.com/watch?v=1SfUMQ1yTY8
https://www.youtube.com/watch?v=7Q6n1vqUrF4
https://www.youtube.com/watch?v=YKHdD4AKZ-c
https://www.youtube.com/watch?v=8WpnDIKQN-E
https://www.youtube.com/watch?v=m6j20_hNlyE
https://www.youtube.com/watch?v=swQLziqWgus"""

    # Process the links
    process_links(youtube_links)
