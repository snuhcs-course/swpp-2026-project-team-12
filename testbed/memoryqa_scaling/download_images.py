"""Public photo download only: no credentials, LLM, SQL or Graphiti access."""
import argparse
from lib.download import download_images

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", help="Optional flat image cache directory")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--image-id", action="append", help="Download only these manifest IDs")
    args = parser.parse_args()
    download_images(directory=args.directory, workers=args.workers, ids=args.image_id)
