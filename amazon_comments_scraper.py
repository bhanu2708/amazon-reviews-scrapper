import argparse
import errno
from time import sleep
import json
import logging
import os
import re
import requests
from bs4 import BeautifulSoup
import math
import textwrap

AMAZON_BASE_URL='https://www.amazon.in'
OUTPUT_DIR = 'comments'

class BannedException(Exception):
    pass

if not os.path.exists(OUTPUT_DIR):# makes the output directory if it doesnt exist
    os.makedirs(OUTPUT_DIR)


def get_reviews_filename(product_id):
    filename = os.path.join(OUTPUT_DIR, '{}.json'.format(product_id))
    exist = os.path.isfile(filename)
    return filename, exist


def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc:
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise


def persist_comment_to_disk(reviews):
    if len(reviews) == 0:
        return False
    product_id_set = set([r['product_id'] for r in reviews])
    assert len(product_id_set) == 1, 'all product ids should be the same in the reviews list.'
    product_id = next(iter(product_id_set))
    output_filename, exist = get_reviews_filename(product_id)
    if exist:
        return False
    mkdir_p(OUTPUT_DIR)
    with open(output_filename, 'w', encoding='utf-8') as fp:
        json.dump(reviews, fp, sort_keys=True, indent=4, ensure_ascii=False)
    return True


def extract_product_id(link_from_main_page):
    # e.g. B01H8A7Q42
    p_id = -1
    tags = ['/dp/', '/gp/product/']
    for tag in tags:
        try:
            p_id = link_from_main_page[link_from_main_page.index(tag) + len(tag):].split('/')[0]
        except:
            pass
    m = re.match('[A-Z0-9]{10}', p_id)
    if m:
        return m.group()
    else:
        return None


def get_soup(url):
    if AMAZON_BASE_URL not in url:
        url = AMAZON_BASE_URL + url
    nap_time_sec = 1
    logging.debug('Script is going to sleep for {} (Amazon throttling). ZZZzzzZZZzz.'.format(nap_time_sec))
    sleep(nap_time_sec)
    header = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/43.0.2357.134 Safari/537.36'
    }
    logging.debug('-> to Amazon : {}'.format(url))
    out = requests.get(url, headers=header)
    assert out.status_code == 200
    soup = BeautifulSoup(out.content, 'lxml')
    if 'captcha' in str(soup):
        raise BannedException('Your bot has been detected. Please wait a while.')
    return soup

def get_product_reviews_url(item_id, page_number=None):# gets the link for the reviews page
    if not page_number:
        page_number = 1
    return AMAZON_BASE_URL + '/product-reviews/{}/ref=' \
                             'cm_cr_arp_d_paging_btm_1?ie=UTF8&reviewerType=all_reviews' \
                             '&showViewpoints=1&sortBy=recent&pageNumber={}'.format(
        item_id, page_number)


def get_comments_based_on_keyword(search):
    logging.info('SEARCH = {}'.format(search))
    url = AMAZON_BASE_URL + '/s/ref=nb_sb_noss_2?url=search-alias%3Daps&field-keywords=' + \
          search + '&rh=i%3Aaps%2Ck%3A' + search
    soup = get_soup(url)

    product_ids = [div.attrs['data-asin'] for div in soup.find_all('div') if 'data-index' in div.attrs]
    logging.info('Found {} items.'.format(len(product_ids)))
    for product_id in product_ids:
        logging.info('product_id is {}.'.format(product_id))
        reviews = get_comments_with_product_id(product_id)
        logging.info('Fetched {} reviews.'.format(len(reviews)))
        persist_comment_to_disk(reviews)


def get_comments_with_product_id(product_id):# it will get all the reviews for the product_id
    reviews = list()
    if product_id is None:
        return reviews
    if not re.match('^[A-Z0-9]{10}$', product_id):
        return reviews

    product_reviews_link = get_product_reviews_url(product_id)
    so = get_soup(product_reviews_link)
    max_page_number = so.find(attrs={'data-hook': 'total-review-count'})
    if max_page_number is None:
        return reviews
    max_page_number = ''.join([el for el in max_page_number.text if el.isdigit()])
    max_page_number = int(max_page_number) if max_page_number else 1

    max_page_number *= 0.1  # displaying 10 results per page.
    max_page_number = math.ceil(max_page_number)

    for page_number in range(1, max_page_number + 1):
        if page_number > 1:
            product_reviews_link = get_product_reviews_url(product_id, page_number)
            so = get_soup(product_reviews_link)

        cr_review_list_so = so.find(id='cm_cr-review_list')

        if cr_review_list_so is None:
            logging.info('No reviews for this item.')
            break

        reviews_list = cr_review_list_so.find_all('div', {'data-hook': 'review'})

        if len(reviews_list) == 0:
            logging.info('No more reviews to unstack.')
            break

        for review in reviews_list:
            rating = review.find(attrs={'data-hook': 'review-star-rating'}).attrs['class'][2].split('-')[-1].strip()
            body = review.find(attrs={'data-hook': 'review-body'}).text.strip()
            title = review.find(attrs={'data-hook': 'review-title'}).text.strip()
            review_date = review.find(attrs={'data-hook': 'review-date'}).text.strip()

            logging.info('***********************************************')
            logging.info('TITLE    = ' + title)
            logging.info('RATING   = ' + rating)
            logging.info('CONTENT  = ' + '\n'.join(textwrap.wrap(body, 80)))
            logging.info('REVIEW DATE  = ' + review_date if review_date else '')
            logging.info('***********************************************\n')
            reviews.append({'title': title,
                            'rating': rating,
                            'body': body,
                            'product_id': product_id,
                            'review_date': review_date,
                           })
    return reviews

def run(search, input_product_ids_filename):
    if input_product_ids_filename is not None:
        with open(input_product_ids_filename, 'r') as r:
            product_ids = [p.strip() for p in r.readlines()]
            logging.info('{} product ids were found.'.format(len(product_ids)))
            reviews_counter = 0
            for product_id in product_ids:
                _, exist = get_reviews_filename(product_id)
                if exist:
                    logging.info('product id [{}] was already fetched. Skipping.'.format(product_id))
                    continue
                reviews = get_comments_with_product_id(product_id)
                reviews_counter += len(reviews)
                logging.info('{} reviews found so far.'.format(reviews_counter))
                persist_comment_to_disk(reviews)
    else:
        default_search = 'mobile phone'
        search = default_search if search is None else search
        reviews = get_comments_based_on_keyword(search)
        persist_comment_to_disk(reviews)


def get_script_arguments():# the arguments for calling the main function
    parser = argparse.ArgumentParser()
    parser.add_argument('-s', '--search')
    parser.add_argument('-i', '--input')
    args = parser.parse_args()
    input_product_ids_filename = args.input
    search = args.search
    return search, input_product_ids_filename


def main():
    search, input_product_ids_filename = get_script_arguments()
    run(search, input_product_ids_filename)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    main()
