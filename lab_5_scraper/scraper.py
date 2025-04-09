"""
Crawler implementation.
"""

import datetime
import json

# pylint: disable=too-many-arguments, too-many-instance-attributes, unused-import, undefined-variable, unused-argument
import pathlib
import re
from typing import Pattern, Union

import lxml
import networkx
import requests
import spacy_udpipe
import stanza
from bs4 import BeautifulSoup

from core_utils.article.article import Article
from core_utils.config_dto import ConfigDTO
from core_utils.constants import CRAWLER_CONFIG_PATH, ASSETS_PATH


def is_valid_url(url: str) -> bool:
    '''
    Checking if url is valid
    Args:
        url: url string to check
    '''
    standard_pattern = r'https?://\S+|www\.\S+'
    if re.match(standard_pattern, url) is None:
        return False
    return True

class IncorrectSeedURLError(TypeError):
    """
    ...
    """
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)
class NumberOfArticlesOutOfRangeError(ValueError):
    """
    ...
    """
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)

class IncorrectNumberOfArticlesError(TypeError):
    """
    ...
    """
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)

class IncorrectHeadersError(TypeError):
    """
    ...
    """
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)

class IncorrectEncodingError(TypeError):
    """
    ...
    """
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)

class IncorrectTimeoutError(ValueError):
    """
    ...
    """
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)


class IncorrectVerifyError(TypeError):
    """
    ...
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)


class Config:
    """
    Class for unpacking and validating configurations.
    """

    def __init__(self, path_to_config: pathlib.Path) -> None:
        """
        Initialize an instance of the Config class.

        Args:
            path_to_config (pathlib.Path): Path to configuration.
        """
        self.path_to_config = path_to_config
        self._validate_config_content()
        prepare_environment(ASSETS_PATH)
        values = self._extract_config_content()
        self._seed_urls = values.seed_urls
        self._num_articles = values.total_articles
        self._timeout = values.timeout
        self._headers = values.headers
        self._encoding = values.encoding
        self._should_verify_certificate = values.should_verify_certificate
        self._headless_mode = values.headless_mode

    def _extract_config_content(self) -> ConfigDTO:
        """
        Get config values.

        Returns:
            ConfigDTO: Config values
        """
        with open(self.path_to_config, 'r', encoding='utf-8') as file:
            config_values_dict = json.load(file)
            config_values = ConfigDTO(config_values_dict['seed_urls'],
                                      config_values_dict['total_articles_to_find_and_parse'],
                                      config_values_dict['headers'],
                                      config_values_dict['encoding'],
                                      config_values_dict['timeout'],
                                      config_values_dict['should_verify_certificate'],
                                      config_values_dict['headless_mode'])
        return config_values

    def _validate_config_content(self) -> None:
        """
        Ensure configuration parameters are not corrupt.
        """
        with open(self.path_to_config, 'r', encoding='utf-8') as file:
            config_values_dict = json.load(file)

            if (not (isinstance(config_values_dict['seed_urls'], list)
                     and all(isinstance(seed_url, str)
                             for seed_url in config_values_dict['seed_urls']))):
                raise IncorrectSeedURLError('Seed URLs must be a list of strings')
            for seed_url in config_values_dict['seed_urls']:
                if not is_valid_url(seed_url):
                    raise IncorrectSeedURLError(
                        'seed URL does not match standard pattern "https?://(www.)?"')

            if (not (isinstance(config_values_dict['total_articles_to_find_and_parse'], int) and
                     config_values_dict['total_articles_to_find_and_parse'] >= 0) or
                    isinstance(config_values_dict['total_articles_to_find_and_parse'], bool)):
                raise IncorrectNumberOfArticlesError(
                    'total number of articles to parse is not integer or less than 0')

            if config_values_dict['total_articles_to_find_and_parse'] > 150:
                raise NumberOfArticlesOutOfRangeError(
                    'total number of articles is out of range from 1 to 150')

            if not isinstance(config_values_dict['headers'], dict):
                raise IncorrectHeadersError('headers are not in a form of dictionary')

            if not isinstance(config_values_dict['encoding'], str):
                raise IncorrectEncodingError('encoding must be specified as a string')

            if (not isinstance(config_values_dict['timeout'], int) or
                    config_values_dict['timeout'] not in range(61)):
                raise IncorrectTimeoutError('timeout value must be a positive integer less than 60')

            if not isinstance(config_values_dict['should_verify_certificate'], bool):
                raise IncorrectVerifyError('verify certificate value must either be True or False')

            if not isinstance(config_values_dict['headless_mode'], bool):
                raise IncorrectVerifyError('headless mode value must either be True or False')

    def get_seed_urls(self) -> list[str]:
        """
        Retrieve seed urls.

        Returns:
            list[str]: Seed urls
        """
        return self._seed_urls

    def get_num_articles(self) -> int:
        """
        Retrieve total number of articles to scrape.

        Returns:
            int: Total number of articles to scrape
        """
        return self._num_articles

    def get_headers(self) -> dict[str, str]:
        """
        Retrieve headers to use during requesting.

        Returns:
            dict[str, str]: Headers
        """
        return self._headers

    def get_encoding(self) -> str:
        """
        Retrieve encoding to use during parsing.

        Returns:
            str: Encoding
        """
        return self._encoding

    def get_timeout(self) -> int:
        """
        Retrieve number of seconds to wait for response.

        Returns:
            int: Number of seconds to wait for response
        """
        return self._timeout

    def get_verify_certificate(self) -> bool:
        """
        Retrieve whether to verify certificate.

        Returns:
            bool: Whether to verify certificate or not
        """
        return self._should_verify_certificate

    def get_headless_mode(self) -> bool:
        """
        Retrieve whether to use headless mode.

        Returns:
            bool: Whether to use headless mode or not
        """
        return self._headless_mode


def make_request(url: str, config: Config) -> requests.models.Response:
    """
    Deliver a response from a request with given configuration.

    Args:
        url (str): Site url
        config (Config): Configuration

    Returns:
        requests.models.Response: A response from a request
    """
    response = requests.get(url,headers=config.get_headers(),
                            timeout=config.get_timeout(),
                            verify=config.get_verify_certificate())
    return response



class Crawler:
    """
    Crawler implementation.
    """

    #: Url pattern
    url_pattern: Union[Pattern, str]

    def __init__(self, config: Config) -> None:
        """
        Initialize an instance of the Crawler class.

        Args:
            config (Config): Configuration
        """
        self.config = config
        self.urls = []

    def _extract_url(self, article_bs: BeautifulSoup) -> str:
        """
        Find and retrieve url from HTML.

        Args:
            article_bs (bs4.BeautifulSoup): BeautifulSoup instance

        Returns:
            str: Url from HTML
        """
        url_from_html = ''
        for url in article_bs.find_all('a', href=True):
            url_href = url['href']
            if url not in self.urls and 'gtrksakha.ru/news' in url_href:
                url_from_html = url_href
                break
        return url_from_html



    def find_articles(self) -> None:
        """
        Find articles.
        """
        for seed_url in self.config.get_seed_urls():
            response = make_request(seed_url, self.config)
            if response.status_code == 200:
                article_bs = BeautifulSoup(response.text, 'lxml')
                extracted_url = self._extract_url(article_bs)
                if is_valid_url(extracted_url):
                    self.urls.append(extracted_url)


    def get_search_urls(self) -> list:
        """
        Get seed_urls param.

        Returns:
            list: seed_urls param
        """
        return self.config.get_seed_urls()


# 10
# 4, 6, 8, 10


class HTMLParser:
    """
    HTMLParser implementation.
    """

    def __init__(self, full_url: str, article_id: int, config: Config) -> None:
        """
        Initialize an instance of the HTMLParser class.

        Args:
            full_url (str): Site url
            article_id (int): Article id
            config (Config): Configuration
        """

    def _fill_article_with_text(self, article_soup: BeautifulSoup) -> None:
        """
        Find text of article.

        Args:
            article_soup (bs4.BeautifulSoup): BeautifulSoup instance
        """

    def _fill_article_with_meta_information(self, article_soup: BeautifulSoup) -> None:
        """
        Find meta information of article.

        Args:
            article_soup (bs4.BeautifulSoup): BeautifulSoup instance
        """

    def unify_date_format(self, date_str: str) -> datetime.datetime:
        """
        Unify date format.

        Args:
            date_str (str): Date in text format

        Returns:
            datetime.datetime: Datetime object
        """

    def parse(self) -> Union[Article, bool, list]:
        """
        Parse each article.

        Returns:
            Union[Article, bool, list]: Article instance
        """


def prepare_environment(base_path: Union[pathlib.Path, str]) -> None:
    """
    Create ASSETS_PATH folder if no created and remove existing folder.

    Args:
        base_path (Union[pathlib.Path, str]): Path where articles stores
    """
    try:
        pathlib.Path(base_path).mkdir(parents=True)
    except FileExistsError:
        for asset in pathlib.Path(base_path).iterdir():
            asset.unlink()
        pathlib.Path(base_path).rmdir()
        pathlib.Path(base_path).mkdir(parents=True)




def main() -> None:
    """
    Entrypoint for scrapper module.
    """
    # space for creation


if __name__ == "__main__":
    main()
