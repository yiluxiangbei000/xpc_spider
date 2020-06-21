# -*- coding: utf-8 -*-

# Define here the models for your spider middleware
#
# See documentation in:
# https://docs.scrapy.org/en/latest/topics/spider-middleware.html
import redis
from scrapy import signals
from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.exceptions import NotConfigured
from scrapy.utils.response import response_status_message
import time
import random
from twisted.internet.error import ConnectionRefusedError, TimeoutError

from collections import defaultdict

class XpcSpiderMiddleware:
    # Not all methods need to be defined. If a method is not defined,
    # scrapy acts as if the spider middleware does not modify the
    # passed objects.

    @classmethod
    def from_crawler(cls, crawler):
        # This method is used by Scrapy to create your spiders.
        s = cls()
        crawler.signals.connect(s.spider_opened, signal=signals.spider_opened)
        return s

    def process_spider_input(self, response, spider):
        # Called for each response that goes through the spider
        # middleware and into the spider.

        # Should return None or raise an exception.
        return None

    def process_spider_output(self, response, result, spider):
        # Called with the results returned from the Spider, after
        # it has processed the response.

        # Must return an iterable of Request, dict or Item objects.
        for i in result:
            yield i

    def process_spider_exception(self, response, exception, spider):
        # Called when a spider or process_spider_input() method
        # (from other spider middleware) raises an exception.

        # Should return either None or an iterable of Request, dict
        # or Item objects.
        pass

    def process_start_requests(self, start_requests, spider):
        # Called with the start requests of the spider, and works
        # similarly to the process_spider_output() method, except
        # that it doesn’t have a response associated.

        # Must return only requests (not items).
        for r in start_requests:
            yield r

    def spider_opened(self, spider):
        spider.logger.info('Spider opened: %s' % spider.name)


class XpcDownloaderMiddleware:
    # Not all methods need to be defined. If a method is not defined,
    # scrapy acts as if the downloader middleware does not modify the
    # passed objects.

    @classmethod
    def from_crawler(cls, crawler):
        # This method is used by Scrapy to create your spiders.
        s = cls()
        crawler.signals.connect(s.spider_opened, signal=signals.spider_opened)
        return s

    def process_request(self, request, spider):
        # Called for each request that goes through the downloader
        # middleware.

        # Must either:
        # - return None: continue processing this request
        # - or return a Response object
        # - or return a Request object
        # - or raise IgnoreRequest: process_exception() methods of
        #   installed downloader middleware will be called
        return None

    def process_response(self, request, response, spider):
        # Called with the response returned from the downloader.

        # Must either;
        # - return a Response object
        # - return a Request object
        # - or raise IgnoreRequest
        return response

    def process_exception(self, request, exception, spider):
        # Called when a download handler or a process_request()
        # (from other downloader middleware) raises an exception.

        # Must either:
        # - return None: continue processing this exception
        # - return a Response object: stops process_exception() chain
        # - return a Request object: stops process_exception() chain
        pass

    def spider_opened(self, spider):
        spider.logger.info('Spider opened: %s' % spider.name)


class TooManyRequestsRetryMiddleware(RetryMiddleware):

    def __init__(self, crawler):
        super(TooManyRequestsRetryMiddleware, self).__init__(crawler.settings)
        self.crawler = crawler

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def process_response(self, request, response, spider):
        if request.meta.get('dont_retry', False):
            return response
        elif response.status == 429:
            self.crawler.engine.pause()
            time.sleep(10) # If the rate limit is renewed in a minute, put 60 seconds, and so on.
            self.crawler.engine.unpause()
            reason = response_status_message(response.status)
            return self._retry(request, reason, spider) or response
        elif response.status in self.retry_http_codes:
            reason = response_status_message(response.status)
            return self._retry(request, reason, spider) or response
        return response

class RandomProxyMiddleware(object):

    def __init__(self, settings):
        #2.初始化配置及相關變量
        #self.proxies = settings.getlist('PROXIES')  之前從配置中讀取
        #改成從Redis中讀取
        self.r = redis.Redis(host='127.0.0.1')
        self.proxy_key = settings.get('PROXY_REDIS_KEY')
        self.max_failed = 3
        self.proxy_stats_key = self.proxy_key + '_stats'

    @property
    def proxies(self):
        return [i.decode('utf-8') for i in self.r.lrange(self.proxy_key, 0, -1)]

    @classmethod
    def from_crawler(cls, crawler):
        #1.創建中間件對象
        if not crawler.settings.getbool('HTTPPROXY_ENABLED'):
            raise NotConfigured
        return cls(crawler.settings)

    def process_request(self, request, spider):
        #3.每一個ruquest對象分配ip
        if self.proxies and not request.meta.get('proxy'):
            request.meta['proxy'] = random.choice(self.proxies)
            print('use %s as current proxy' % request.meta['proxy'])

    def process_response(self, request, response, spider):
        #4.請求成功則調用process_response
        cur_proxy = request.meta.get('proxy')
        #是否對被對方封禁
        if response.status in (401, 403):
            print('%s got wrong code %s times' % (cur_proxy, self.proxy_stats_key))
            #self.stats[cur_proxy] += 1
            self.r.hincrby(self.proxy_stats_key, cur_proxy, 1)

        failed_time = self.r.hget(cur_proxy, self.proxy_stats_key) or 0
        if int(failed_time) >= self.max_failed:
            print('got wrong http code (%s) when use %s'
                  % (response.status, cur_proxy))
            del request.meta['proxy']
            self.remove_proxy(cur_proxy)
            #將該請求重新安排調度下載
            return request
        return response

    def process_exception(self, request, exception, spider):
        #4.請求失敗調用process_exception
        cur_proxy = request.meta.get('proxy')
        #如果本次請求使用了代理，並且網絡請求報錯，則認爲該ip出現了問題
        if cur_proxy and isinstance(exception, (ConnectionRefusedError, TimeoutError)):
            print('error (%s) occured when use proxy %s'%(exception, cur_proxy))
            del request.meta['proxy']
            self.remove_proxy(cur_proxy)
            return request

    def remove_proxy(self, proxy):
        print('starting remove proxy: %s' % proxy)
        if proxy in self.proxies:
            self.r.lrem(self.proxy_key, -1, proxy)
            self.r.hdel(self.proxy_stats_key, proxy)
            print('proxy:%s is deleted from proxies list' % proxy)

