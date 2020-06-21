# -*- coding: utf-8 -*-
import scrapy
import json
import re
import random
import string
from scrapy import Request
from xpc.items import CommentItem, PostItem, ComposerItem, CopyrightItem
from scrapy_redis.spiders import RedisSpider
from scrapy_redis.pipelines import RedisPipeline


def strip(s):
    if s:
        return s.strip()
    return ''

def convert_int(s):
    if isinstance(s, str):
        return int(s.replace(',', ''))
    return 0

def convert_int(s):
    if isinstance(s, str):
        return int(s.replace(',', ''))
    return 0


def gen_sessionid():
    return  ''.join([random.choice(string.ascii_lowercase + string.digits)
                     for _ in range(26)])


cookies = dict(
    Authorization = 'CDBE96F4F9B2B74EDF9B2B4062F9B2B896BF9B2B02F08D2D8565'
)


class DiscoverySpider(RedisSpider):
    name = 'discovery'
    allowed_domains = ['xinpianchang.com', 'openapi-vtom.vmovier.com']
    start_urls = ['https://www.xinpianchang.com/channel/index/sort-like?from=navigator']
    page_count = 0

    def parse(self, response):
        #from scrapy.shell import inspect_response()
        #inspect_response(response, self)
        self.page_count += 1
        if self.page_count >= 100:
            cookies.update(PHPSESSID=gen_sessionid())
            self.page_count = 0
        post_list = response.xpath(
            '//ul[@class="video-list"]/li')
        url = 'https://www.xinpianchang.com/a%s?from=ArticleList'
        for post in post_list:
            pid = post.xpath('./@data-articleid').get()
            request = response.follow(url % pid, self.parse_post)
            request.meta['pid'] = pid
            request.meta['thumbnail'] = post.xpath('./a/img/@_src').get()
            yield request

        pages = response.xpath('//div[@class="page"]/a/@href').extract()
        for page in pages:
            yield response.follow(
                'https://www.xinpianchang.com%s' % page, self.parse, cookies=cookies)

    def parse_post(self, response):
        pid = response.meta['pid']
        post = PostItem(pid=pid)
        post['thumbnail'] = response.meta['thumbnail']
        post['title'] = response.xpath(
            '//div[@class="title-wrap"]/h3/text()').get()  #get()==extract()
        vid, = re.findall('vid: \"(\w+)\"\,' ,response.text)
        video_url = 'https://openapi-vtom.vmovier.com/v3/video/%s?expand=resource&usage=xpc_web'
        post['category'] = ''.join([_.strip() for _ in response.xpath(
            '//span[contains(@class,"cate")]//text()').extract()])
        post['created_at'] = response.xpath(
            '//span[contains(@class,"update-time")]/i/text()').get()
        post['play_counts'] = convert_int(response.xpath(
            '//i[contains(@class,"play-count")]/text()').get())
        post['like_counts'] = convert_int(response.xpath(
            '//span[contains(@class,"like-counts")]/text()').get())
        post['description'] = strip(response.xpath(
            '//p[contains(@class, "desc")]/text()').get())


        #多了一步视频地址请求
        request = Request(video_url % vid, callback=self.parse_video)
        request.meta['post'] = post   # 传post给parse_video()
        yield request   #???不明白
        # request即为<GET https://openapi-vtom.vmovier.com/v3/video/5EDE53C61C155?expand=resource&usage=xpc_web>

        comment_url = 'https://app.xinpianchang.com/comments?resource_id=%s&type=article&page=1&per_page=24'
        request = Request(comment_url % pid, callback=self.parse_comment)
        request.meta['pid'] = pid
        yield request


        creator_list = response.xpath('//div[@class="creator-info"]')
        for creator in creator_list:
            c_url, = creator.xpath('./a/@href').extract()
            cid, = re.findall('\/u(\d+)\?' ,c_url)
            request = response.follow('https://www.xinpianchang.com'+c_url, self.parse_composer)
            request.meta['cid'] = cid
            request.meta['dont_merge_cookies'] = True
            yield request

            cr = CopyrightItem()
            cr['pcid'] = '%s_%s' % (pid, cid)
            cr['pid'] = pid
            cr['roles'] = creator.xpath('./a/following-sibling::span[1]/text()').get()
            yield cr

    def parse_video(self, response):
        post = response.meta['post']
        result = json.loads(response.text)
        data = result['data']
        if 'resource' in data:
            post['video'] = data['resource']['default']['url']
        else:
            d = data['third']['data']
            post['video'] = d.get('iframe_url', d.get('swf', ''))  #???
        post['preview'] = result['data']['video']['cover']
        post['duration'] = result['data']['video']['duration']
        yield post

    def parse_comment(self, response):
        comment = CommentItem()
        result = json.loads(response.text)
        for i in result['data']['list']:
            comment['uname'] = i['userInfo']['username']
            comment['cid'] = i['userInfo']['id']
            comment['avatar'] = i['userInfo']['avatar']
            comment['commentid'] = i['id']
            comment['pid'] = i['resource_id']
            comment['content'] = i['content']
            comment['created_at'] = i['addtime']
            comment['like_counts'] = i['count_approve']
            if i['referid'] != 0:
                comment['reply'] = i['referid'] or 0
            yield comment

        next_page = result['data']['next_page_url']
        if next_page is not None:
            yield response.follow(
                'https://app.xinpianchang.com%s' % next_page, self.parse_comment)

    def parse_composer(self, response):
        print('****创作人××××' * 5)
        composer = ComposerItem()

        banner = response.xpath('//div[contains(@class,"banner-linear")]').get()
        composer['cid'] = response.meta['cid']
        composer['banner'] = re.findall('src\=\"(.+?)\"\>', banner)[0]
        composer['avatar'] = re.findall('src\=\"(.+?)\"\>', banner)[1]
        composer['name'] = response.xpath(
            '//p[contains(@class,"creator-name")]/text()').get().strip()
        composer['intro'] = response.xpath(
            '//p[contains(@class,"creator-desc")]/text()').get()
        composer['like_counts'] = convert_int(response.xpath(
            '//span[contains(@class,"like-counts")]/text()').get())
        composer['fans_counts'] = convert_int(response.xpath(
            '//span[contains(@class,"fans-counts")]/text()').get())
        composer['follow_counts'] = convert_int(response.xpath(
            '//span[@class="fw_600 v-center"]/text()').get())
        composer['location'] = response.xpath(
            '//span[contains(@class,"icon-location")]/following-sibling::span[1]/text()').get() or ''
        composer['career'] = response.xpath(
            '//span[contains(@class,"icon-career")]/following-sibling::span[1]/text()').get() or ''
        yield composer




