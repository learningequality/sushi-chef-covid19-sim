#!/usr/bin/env python
import json
import os
import shutil
import sys
import tempfile

from ricecooker.utils import downloader, zip
from ricecooker.chefs import SushiChef
from ricecooker.classes import nodes, files, questions, licenses
from ricecooker.config import LOGGER              # Use LOGGER to print messages
from ricecooker.exceptions import raise_for_invalid_channel
from le_utils.constants import exercises, content_kinds, file_formats, format_presets, languages

# use BeautifulSoup for grabbing data and making changes to the HTML page.
from bs4 import BeautifulSoup

# Run constants
################################################################################
CHANNEL_NAME = "Coronavirus Simulations"                    # Name of Kolibri channel
CHANNEL_SOURCE_ID = "covid19-sim"                           # Unique ID for content source
CHANNEL_DOMAIN = "ncase.me"                                 # Who is providing the content
CHANNEL_LANGUAGE = "en"                                     # Language of channel
CHANNEL_DESCRIPTION = "For anyone of any age curious to explore what happens next in the COVID-19 pandemic, these playable simulations (in 19 different languages) from Marcel Salathé and Nicky Case provide a way to learn about epidemiology, explore how the math of viruses works, and develop our ability to deal with the reality of the pandemic."
CHANNEL_THUMBNAIL = "assets/spread.png"                                    # Local path or url to image file (optional)
CONTENT_ARCHIVE_VERSION = 1

# Additional constants
################################################################################
ROOT_URL = "https://ncase.me/covid-19/"


# The chef subclass
################################################################################
class Covid19SimChef(SushiChef):
    """
    This class converts content from the content source into the format required by Kolibri,
    then uploads the {channel_name} channel to Kolibri Studio.
    Your command line script should call the `main` method as the entry point,
    which performs the following steps:
      - Parse command line arguments and options (run `./sushichef.py -h` for details)
      - Call the `SushiChef.run` method which in turn calls `pre_run` (optional)
        and then the ricecooker function `uploadchannel` which in turn calls this
        class' `get_channel` method to get channel info, then `construct_channel`
        to build the contentnode tree.
    For more info, see https://ricecooker.readthedocs.io
    """
    channel_info = {
        'CHANNEL_SOURCE_DOMAIN': CHANNEL_DOMAIN,
        'CHANNEL_SOURCE_ID': CHANNEL_SOURCE_ID,
        'CHANNEL_TITLE': CHANNEL_NAME,
        'CHANNEL_LANGUAGE': CHANNEL_LANGUAGE,
        'CHANNEL_THUMBNAIL': CHANNEL_THUMBNAIL,
        'CHANNEL_DESCRIPTION': CHANNEL_DESCRIPTION,
    }
    DATA_DIR = os.path.abspath('chefdata')
    ZIP_DIR = os.path.join(DATA_DIR, 'zips')
    DOWNLOADS_DIR = os.path.join(DATA_DIR, 'downloads')
    ARCHIVE_DIR = os.path.join(DOWNLOADS_DIR, 'archive_{}'.format(CONTENT_ARCHIVE_VERSION))
    ARCHIVE_DATA = os.path.join(ARCHIVE_DIR, 'downloads.json')
    # Your chef subclass can override/extend the following method:
    # get_channel: to create ChannelNode manually instead of using channel_info
    # pre_run: to perform preliminary tasks, e.g., crawling and scraping website
    # __init__: if need to customize functionality or add command line arguments

    def download_content(self):
        LOGGER.info("Calling download_content")
        self.data = {}
        if os.path.exists(self.ARCHIVE_DATA):
            self.data = json.loads(open(self.ARCHIVE_DATA).read())

        self.client = downloader.ArchiveDownloader(self.ARCHIVE_DIR)

        # scrape same domain links one level deep
        link_policy = {'policy': 'scrape', 'scope': 'same_domain', 'levels': 1}
        if not 'English' in self.data or not os.path.exists(self.data['English']['index_path']):
            self.data['English'] = self.client.get_page(ROOT_URL, link_policy=link_policy, relative_links=True)

        # The links to the translated versions are contained in the English index page, so we have to
        # parse it to retrieve them
        soup = self.client.get_page_soup(ROOT_URL)
        translations = soup.find('div', {'id': 'translations'})
        if translations:
            links = translations.select('a[href]')
            for link in links:
                lang = link.text.strip()
                LOGGER.info("Lang: '{}'".format(lang))

                # ignore the "Help make a translation" link
                if 'translation' in lang:
                    continue

                # Don't re-download each time
                if not lang in self.data or not os.path.exists(self.data[lang]['index_path']):
                    url = link['href']
                    if not url.endswith('/'):
                        url += '/'
                    self.data[lang] = self.client.get_page(url, link_policy=link_policy, relative_links=True)

                    LOGGER.debug("lang: {}, url: {}".format(lang, url))
        else:
            LOGGER.warning("No translations found?")

        with open(self.ARCHIVE_DATA, 'w') as f:
            json.dump(self.data, f, indent=4)

    def construct_channel(self, *args, **kwargs):
        """
        Creates ChannelNode and build topic tree
        Args:
          - args: arguments passed in on the command line
          - kwargs: extra options passed in as key="value" pairs on the command line
            For example, add the command line option   lang="fr"  and the value
            "fr" will be passed along to `construct_channel` as kwargs['lang'].
        Returns: ChannelNode
        """
        channel = self.get_channel(*args, **kwargs)  # Create ChannelNode from data in self.channel_info

        lang_names = list(self.data.keys())
        lang_names.sort()

        for lang_name in lang_names:
            lang_data = self.data[lang_name]
            LOGGER.info("Creating app for language: {}".format(lang_name))
            lang = languages.getlang_by_native_name(lang_name)
            if lang:
                LOGGER.info("Language: {}".format(lang))
            else:
                LOGGER.warning("Unable to find language for {}".format(lang_name))

            zip_dir = self.client.create_zip_dir_for_page(lang_data['url'])

            soup = self.client.get_page_soup(lang_data['url'])

            # Remove the translation list if found
            translations = soup.find('div', {'id': 'translations'})
            if translations:
                translations.extract()

            # Grab the localized title
            title = soup.find('span', {'id': 'share_title'}).text

            # There is an issue with Kolibri's HTML5 zip support where it doesn't auto-append index.html
            # to URLs that point to the sim subdirectory, so here we add it explicitly.
            links = soup.find_all('iframe')
            # for link in links:
            #     src_attr = 'src'
            #     if link.has_attr('data-src') and not link.has_attr('src'):
            #         src_attr='data-src'
            #         if 'sim?' in link[src_attr]:
            #         # print("Found link {}".format(link[src_attr]))
            #             link[src_attr] = link[src_attr].replace('sim?', 'sim/index.html?')
            #             print# ("Link is now {}".format(link[src_attr]))
                # else:
                #     print("Not replacing link {}".format(link[src_attr]))

            # Save the modified index.html page
            thumbnail = None
            for resource in lang_data['resources']:
                if 'dp3t.png' in resource:
                    thumbnail = os.path.join(zip_dir, resource)
                    break

            with open(os.path.join(zip_dir, 'index.html'), 'wb') as f:
                f.write(soup.prettify(encoding='utf-8'))

            # create_predictable_zip ensures that the ZIP file does not change each time it's created. This
            # ensures that the zip doesn't get re-downloaded just because zip metadata changed.
            zip_file = zip.create_predictable_zip(zip_dir)
            zip_name = lang.primary_code if lang else lang_name
            zip_filename = os.path.join(self.ZIP_DIR, "{}.zip".format(zip_name))
            os.makedirs(os.path.dirname(zip_filename), exist_ok=True)
            os.rename(zip_file, zip_filename)

            topic = nodes.TopicNode(source_id=lang_name, title=lang_name)
            zip_node = nodes.HTML5AppNode(source_id="covid19-sim-{}".format(lang_name),
                                title=title,
                                files=[files.HTMLZipFile(zip_filename)],
                                license=licenses.PublicDomainLicense("Marcel Salathé & Nicky Case"),
                                language=lang,
                                thumbnail=thumbnail
            )
            topic.add_child(zip_node)
            channel.add_child(topic)

        return channel



# CLI
################################################################################
if __name__ == '__main__':
    # This code runs when sushichef.py is called from the command line
    chef = Covid19SimChef()
    chef.main()
