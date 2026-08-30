"""
Created on 2022年3月7日

@author: Jayden21 <jayden0721@163.com>
本软件非开源软件，版权所有者为作者，购买者享有个人使用授权，
但不得向第三方拷贝传播该框架相关内容，非许可禁止公开传播，一经发现将严肃追究法律责任！

实时成交数据
接口：realtime_tick，由于采集和拼接当日以来的成交全历史，因此接口提取数据时需要一定时间，请耐心等待

输入参数

名称	类型	必选	描述
ts_code	str	N	股票代码，需按tushare股票代码标准输入，比如：000001.SZ表示平安银行，600000.SH表示浦发银行，单次只能输入一个股票
src	str	N	数据源 （sina-新浪 dc-东方财富，默认sina）


输出参数

名称	类型	描述
time	str	交易时间
price	float	现价
change	float	价格变动
volume	int	成交量（单位：手）
amount	int	成交金额（元）
type	str	类型：买入/卖出/中性
"""
from collections import Counter as _Counter
import datetime as _datetime
from decimal import Decimal as _Decimal
from decimal import InvalidOperation as _InvalidOperation
import numbers as _numbers
import re as _re
from zoneinfo import ZoneInfo as _ZoneInfo

import pandas as _pd

from basis import *


class RealtimeCodeListRequiredError(ValueError):
    """Raised when a real-time endpoint has no caller-supplied codes."""


class RealtimeTickDateUnverifiedError(ValueError):
    """Raised when an East tick frame has no safe provider-date anchor."""


SHANGHAI_TIMEZONE = _ZoneInfo('Asia/Shanghai')
CN_CONTINUOUS_SESSION_WINDOWS = (
    (_datetime.time(9, 30, 0), _datetime.time(11, 30, 0)),
    (_datetime.time(13, 0, 0), _datetime.time(15, 0, 0)),
)
REALTIME_EVENT_FRESHNESS_TOLERANCE = _datetime.timedelta(minutes=2)
_CANONICAL_CODE = _re.compile(r'[0-9]{6}\.(?:SH|SZ|BJ)')
_TICK_TIME_ALIASES = ('TIME', 'time', 'trade_time')
_TICK_IDENTITY_ALIASES = (
    ('time', _TICK_TIME_ALIASES),
    ('price', ('PRICE', 'price')),
    ('change', ('CHANGE', 'change')),
    ('volume', ('VOLUME', 'volume')),
    ('amount', ('AMOUNT', 'amount')),
    ('type', ('TYPE', 'type')),
)
_CANONICAL_TICK_IDENTITY_ALIASES = tuple(
    (name, (name,))
    for name, _aliases in _TICK_IDENTITY_ALIASES
)
_DECLARED_TICK_IDENTITY_COLUMNS = (
    'trade_date',
    'time',
    'ts_code',
    'src',
    'price',
    'change',
    'volume',
    'amount',
    'type',
)
_QUOTE_CODE_ALIASES = ('TS_CODE', 'ts_code')
_QUOTE_DATE_ALIASES = ('DATE', 'date', 'trade_date')
_QUOTE_TIME_ALIASES = ('TIME', 'time', 'trade_time')
_QUOTE_SOURCE_ALIASES = ('SRC', 'src')


def _now_shanghai():
    return _datetime.datetime.now(SHANGHAI_TIMEZONE)


def _read_shanghai_clock():
    value = _now_shanghai()
    if not isinstance(value, _datetime.datetime) or value.tzinfo is None:
        raise RealtimeTickDateUnverifiedError(
            'realtime_tick clock must be timezone-aware'
        )
    return value.astimezone(SHANGHAI_TIMEZONE)


def _single_alias_column(frame, aliases, label, required=True):
    columns = list(frame.columns)
    matches = [
        alias
        for alias in aliases
        if columns.count(alias)
    ]
    if not matches and not required:
        return None
    if (
        len(matches) != 1
        or columns.count(matches[0]) != 1
    ):
        raise RealtimeTickDateUnverifiedError(
            f'realtime_tick {label} column is ambiguous'
        )
    return matches[0]


def _canonical_code(value, label):
    if (
        type(value) is not str
        or _CANONICAL_CODE.fullmatch(value) is None
    ):
        raise RealtimeTickDateUnverifiedError(
            f'realtime_tick {label} is not a canonical single code'
        )
    return value


def _canonical_provider_date(value):
    if type(value) is not str:
        raise RealtimeTickDateUnverifiedError(
            'realtime_tick quote provider date must be a string'
        )
    if _re.fullmatch(r'[0-9]{8}', value):
        compact = value
        date_format = '%Y%m%d'
    elif _re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        compact = value[:4] + value[5:7] + value[8:]
        date_format = '%Y-%m-%d'
    else:
        raise RealtimeTickDateUnverifiedError(
            'realtime_tick quote provider date is not canonical'
        )
    try:
        parsed = _datetime.datetime.strptime(
            value,
            date_format,
        )
    except ValueError as exc:
        raise RealtimeTickDateUnverifiedError(
            'realtime_tick quote provider date is invalid'
        ) from exc
    if parsed.strftime('%Y%m%d') != compact:
        raise RealtimeTickDateUnverifiedError(
            'realtime_tick quote provider date is invalid'
        )
    return compact


def _canonical_event_time(value, label, allow_quote_space=False):
    if type(value) is not str:
        raise RealtimeTickDateUnverifiedError(
            f'realtime_tick {label} must be a string'
        )
    if allow_quote_space and value.startswith(' '):
        if len(value) != 9:
            raise RealtimeTickDateUnverifiedError(
                f'realtime_tick {label} is not canonical'
            )
        candidate = value[1:]
    else:
        candidate = value
    if (
        _re.fullmatch(
            r'[0-9]{2}:[0-9]{2}:[0-9]{2}',
            candidate,
        )
        is None
    ):
        raise RealtimeTickDateUnverifiedError(
            f'realtime_tick {label} is not canonical'
        )
    hour, minute, second = (
        int(candidate[:2]),
        int(candidate[3:5]),
        int(candidate[6:]),
    )
    if hour > 23 or minute > 59 or second > 59:
        raise RealtimeTickDateUnverifiedError(
            f'realtime_tick {label} is outside clock bounds'
        )
    return candidate


def _require_one_continuous_session(*moments):
    if not moments:
        raise RealtimeTickDateUnverifiedError(
            'realtime_tick call clock is missing'
        )
    if any(
        not isinstance(moment, _datetime.datetime)
        or moment.tzinfo is None
        for moment in moments
    ):
        raise RealtimeTickDateUnverifiedError(
            'realtime_tick call clock is invalid'
        )
    local = [
        moment.astimezone(SHANGHAI_TIMEZONE)
        for moment in moments
    ]
    if any(
        current < previous
        for previous, current in zip(local, local[1:])
    ):
        raise RealtimeTickDateUnverifiedError(
            'realtime_tick call clock moved backwards'
        )
    if len({moment.date() for moment in local}) != 1:
        raise RealtimeTickDateUnverifiedError(
            'realtime_tick call crossed a local date'
        )
    for session_start, session_end in CN_CONTINUOUS_SESSION_WINDOWS:
        if all(
            session_start <= moment.time() <= session_end
            for moment in local
        ):
            return None
    raise RealtimeTickDateUnverifiedError(
        'realtime_tick call is outside one continuous CN session'
    )


def _continuous_session_index(moment):
    if (
        not isinstance(moment, _datetime.datetime)
        or moment.tzinfo is None
    ):
        raise RealtimeTickDateUnverifiedError(
            'realtime_tick scheduler clock is invalid'
        )
    local = moment.astimezone(SHANGHAI_TIMEZONE)
    for index, (session_start, session_end) in enumerate(
        CN_CONTINUOUS_SESSION_WINDOWS
    ):
        if session_start <= local.time() <= session_end:
            return index
    return None


def _canonical_tick_number(value, label):
    if (
        isinstance(value, bool)
        or not isinstance(value, (_numbers.Real, _Decimal))
    ):
        raise RealtimeTickDateUnverifiedError(
            f'realtime_tick {label} must be numeric'
        )
    try:
        normalized = _Decimal(str(value))
    except (_InvalidOperation, ValueError) as exc:
        raise RealtimeTickDateUnverifiedError(
            f'realtime_tick {label} must be numeric'
        ) from exc
    if not normalized.is_finite():
        raise RealtimeTickDateUnverifiedError(
            f'realtime_tick {label} must be finite'
        )
    return normalized


def _canonical_tick_type(value):
    if type(value) is not str or not value.strip():
        raise RealtimeTickDateUnverifiedError(
            'realtime_tick type must be a nonblank string'
        )
    return value


def _tick_identity_counter(
    frame,
    provider_date,
    expected_code,
    expected_source,
    *,
    canonical_columns=False,
):
    if not isinstance(frame, _pd.DataFrame) or len(frame) == 0:
        raise RealtimeTickDateUnverifiedError(
            'realtime_tick response is empty or malformed'
        )
    provider_date = _canonical_provider_date(provider_date)
    expected_code = _canonical_code(expected_code, 'identity code')
    if type(expected_source) is not str or expected_source != 'dc':
        raise RealtimeTickDateUnverifiedError(
            'realtime_tick identity source must be exactly dc'
        )
    alias_families = (
        _CANONICAL_TICK_IDENTITY_ALIASES
        if canonical_columns
        else _TICK_IDENTITY_ALIASES
    )
    if canonical_columns and (
        len(frame.columns) != len(_DECLARED_TICK_IDENTITY_COLUMNS)
        or set(frame.columns) != set(_DECLARED_TICK_IDENTITY_COLUMNS)
    ):
        raise RealtimeTickDateUnverifiedError(
            'realtime_tick cleaned frame must contain exactly the '
            'nine declared identity columns'
        )
    selected_columns = {
        name: _single_alias_column(
            frame,
            aliases,
            f'{name} identity',
        )
        for name, aliases in alias_families
    }
    selected_values = {
        name: frame[column].tolist()
        for name, column in selected_columns.items()
    }
    if canonical_columns:
        context_columns = {
            name: _single_alias_column(
                frame,
                (name,),
                f'{name} identity',
            )
            for name in ('trade_date', 'ts_code', 'src')
        }
        context_values = {
            name: frame[column].tolist()
            for name, column in context_columns.items()
        }
    else:
        context_values = None
    identities = _Counter()
    for position in range(len(frame)):
        if context_values is None:
            row_date = provider_date
            row_code = expected_code
            row_source = expected_source
        else:
            row_date = _canonical_provider_date(
                context_values['trade_date'][position]
            )
            row_code = _canonical_code(
                context_values['ts_code'][position],
                'cleaned identity code',
            )
            row_source = context_values['src'][position]
            if (
                row_date != provider_date
                or row_code != expected_code
                or type(row_source) is not str
                or row_source != expected_source
            ):
                raise RealtimeTickDateUnverifiedError(
                    'realtime_tick cleaned provider identity changed'
                )
        event_time = _canonical_event_time(
            selected_values['time'][position],
            'tick time',
        )
        price = _canonical_tick_number(
            selected_values['price'][position],
            'price',
        )
        change = _canonical_tick_number(
            selected_values['change'][position],
            'change',
        )
        volume = _canonical_tick_number(
            selected_values['volume'][position],
            'volume',
        )
        amount = _canonical_tick_number(
            selected_values['amount'][position],
            'amount',
        )
        tick_type = _canonical_tick_type(
            selected_values['type'][position]
        )
        identities[
            (
                row_date,
                event_time,
                row_code,
                row_source,
                price,
                change,
                volume,
                amount,
                tick_type,
            )
        ] += 1
    return identities


def _fresh_event_datetime(provider_date, event_time, observed_at, label):
    event_at = _datetime.datetime.strptime(
        provider_date + event_time,
        '%Y%m%d%H:%M:%S',
    ).replace(tzinfo=SHANGHAI_TIMEZONE)
    if event_at > observed_at:
        raise RealtimeTickDateUnverifiedError(
            f'realtime_tick {label} is in the future'
        )
    if (
        observed_at - event_at
        > REALTIME_EVENT_FRESHNESS_TOLERANCE
    ):
        raise RealtimeTickDateUnverifiedError(
            f'realtime_tick {label} is stale'
        )
    return event_at


def _max_tick_time(frame):
    if not isinstance(frame, _pd.DataFrame) or len(frame) == 0:
        raise RealtimeTickDateUnverifiedError(
            'realtime_tick response is empty or malformed'
        )
    time_column = _single_alias_column(
        frame,
        _TICK_TIME_ALIASES,
        'tick time',
    )
    times = [
        _canonical_event_time(value, 'tick time')
        for value in frame[time_column].tolist()
    ]
    return max(times)


def _quote_anchor_values(frame, expected_code, expected_source):
    if not isinstance(frame, _pd.DataFrame) or len(frame) != 1:
        raise RealtimeTickDateUnverifiedError(
            'realtime_tick quote anchor must contain exactly one row'
        )
    code_column = _single_alias_column(
        frame,
        _QUOTE_CODE_ALIASES,
        'quote code',
    )
    date_column = _single_alias_column(
        frame,
        _QUOTE_DATE_ALIASES,
        'quote date',
    )
    time_column = _single_alias_column(
        frame,
        _QUOTE_TIME_ALIASES,
        'quote time',
    )
    source_column = _single_alias_column(
        frame,
        _QUOTE_SOURCE_ALIASES,
        'quote source',
        required=False,
    )
    row = frame.iloc[0]
    quote_code = _canonical_code(
        row[code_column],
        'quote code',
    )
    if quote_code != expected_code:
        raise RealtimeTickDateUnverifiedError(
            'realtime_tick quote code does not match the tick call'
        )
    if source_column is not None:
        quote_source = row[source_column]
        if type(quote_source) is not str or quote_source != expected_source:
            raise RealtimeTickDateUnverifiedError(
                'realtime_tick quote source does not match src=dc'
            )
    provider_date = _canonical_provider_date(row[date_column])
    quote_time = _canonical_event_time(
        row[time_column],
        'quote time',
        allow_quote_space=True,
    )
    return provider_date, quote_time


class get_rt_stk_tick__east(ts2db_rt_by_src_and_codelist_template):
    def ts2db_init(self):  # 初始化的工作都放在这里
        self.params.table_name = 'hq_rt_stk_tick__east'  # 保存到数据库的库名
        self.params.ts_api = self.params.ts.realtime_tick  # 告诉框架本接口对应的tushare的接口函数
        self.params.table_name_cn = '实时_逐笔成交__东财'  # 接口名称

        self.params.src = 'dc'  # 数据源 （sina-新浪 dc-东方财富，默认sina）
        self.params.how_many_codes_onetime = 1  # 一次调用最多获取多少个代码对应的数据（这个接口只能一只一只得来）
        self.params.time_gap = 3  # 间隔多少秒抓一次数据
        self.params.rt_deal_duplicate_data = True  # 是否实时内存去重数据
        self.params.deal_duplicate_strict_date_scope = True
        self.params.str_time = '09:30:00'
        self.params.end_time = '15:00:00'
        self._provider_trade_dates = set()
        self._successful_tick_write_count = 0
        self.realtime_tick_call_started_at = None
        self.realtime_tick_call_ended_at = None
        self.realtime_quote_anchor_started_at = None
        self.realtime_quote_anchor_ended_at = None
        self._inside_realtime_tick_get_agent = False
        self._tick_called_in_get_agent = False
        self._quote_anchor_called_in_get_agent = False
        self._provider_error_in_get_agent = None
        self._clear_realtime_tick_date_verification()
        # -------------------------------------------数据初始化工作--------------------------------------------------------
        codelist = getattr(self.params, 'codelist', None)
        if codelist is None or len(codelist) == 0:
            raise RealtimeCodeListRequiredError(
                'codelist must be supplied by the realtime caller'
            )
        self.params.codelist = codelist

        # -------------------------------------------定义数据库索引--------------------------------------------------------
        # 自动维护数据库表的索引，提高数据访问性能，一般能提高至少一个数量级；
        # 可根据查询数据的需要自定义一些索引，提高查询性能（只要在这里定义了，框架会自动帮你维护索引）
        # 这里一个列表即一个索引，需建立多个索引则配置多个列表，比如：self.params.db_indexes = [['ts_code'], ['trade_date', 'ts_code']]
        # 注意：至少把下面去重的键值，建立一个索引
        self.params.db_indexes = [['ts_code'],
                                  ['trade_date', 'ts_code'],
                                  ['trade_date', 'ts_code', 'src', 'time']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        # 数据整理函数，定义后框架会自动调用，以进行数据整理
        # 数据整理是根据抓取数据的时间段进行整理的，如需指定特定时间段进行整理，请使用“单独运行数据整理.py”程序
        # 数据去重，配置好该数据接口的唯一键字组合后，框架会以此进行去重处理
        self.params.deal_data__duplicate_data_key = \
            'trade_date, time, ts_code, src, price, change, volume, amount, type'

    def _clear_realtime_tick_date_verification(self):
        self._verified_tick_frame_id = None
        self._verified_tick_provider_date = None
        self._verified_tick_code = None
        self._verified_tick_source = None
        self._verified_tick_max_time = None
        self._verified_tick_cleaned = False
        self._verified_tick_identity_counter = None

    def _verified_context_for_clean(self):
        if (
            self._verified_tick_frame_id is None
            or id(self.df) != self._verified_tick_frame_id
            or self._verified_tick_provider_date is None
            or self._verified_tick_code is None
            or self._verified_tick_source != 'dc'
            or self.realtime_tick_call_ended_at is None
        ):
            raise RealtimeTickDateUnverifiedError(
                'realtime_tick frame has no verified provider date'
            )
        if (
            self.params.code != self._verified_tick_code
            or self.params.src != self._verified_tick_source
        ):
            raise RealtimeTickDateUnverifiedError(
                'realtime_tick code or source changed after verification'
            )
        current_max_time = _max_tick_time(self.df)
        if current_max_time != self._verified_tick_max_time:
            raise RealtimeTickDateUnverifiedError(
                'realtime_tick frame changed after date verification'
            )
        current_identities = _tick_identity_counter(
            self.df,
            self._verified_tick_provider_date,
            self._verified_tick_code,
            self._verified_tick_source,
        )
        if (
            self._verified_tick_identity_counter is None
            or current_identities
            != self._verified_tick_identity_counter
        ):
            raise RealtimeTickDateUnverifiedError(
                'realtime_tick raw identity changed after verification'
            )
        _fresh_event_datetime(
            self._verified_tick_provider_date,
            current_max_time,
            self.realtime_tick_call_ended_at,
            'maximum tick time',
        )
        return (
            self._verified_tick_provider_date,
            self._verified_tick_code,
            self._verified_tick_source,
        )

    def _verified_context_for_write(self):
        if (
            not self._verified_tick_cleaned
            or self._verified_tick_provider_date is None
            or self._verified_tick_code is None
            or self._verified_tick_source != 'dc'
            or not isinstance(self.df, _pd.DataFrame)
            or len(self.df) == 0
            or self._verified_tick_identity_counter is None
        ):
            raise RealtimeTickDateUnverifiedError(
                'realtime_tick write has no verified provider date'
            )
        if (
            self.params.code != self._verified_tick_code
            or self.params.src != self._verified_tick_source
        ):
            raise RealtimeTickDateUnverifiedError(
                'realtime_tick code or source changed before write'
            )
        current_identities = _tick_identity_counter(
            self.df,
            self._verified_tick_provider_date,
            self._verified_tick_code,
            self._verified_tick_source,
            canonical_columns=True,
        )
        if any(
            count
            > self._verified_tick_identity_counter.get(identity, 0)
            for identity, count in current_identities.items()
        ):
            raise RealtimeTickDateUnverifiedError(
                'realtime_tick cleaned identity is not a verified '
                'nonempty row-submultiset'
            )
        return (
            self._verified_tick_provider_date,
            self._verified_tick_code,
            self._verified_tick_source,
        )

    def ts2db_get_data_agent(self):
        self._inside_realtime_tick_get_agent = True
        self._tick_called_in_get_agent = False
        self._quote_anchor_called_in_get_agent = False
        self._provider_error_in_get_agent = None
        try:
            return super().ts2db_get_data_agent()
        finally:
            self._inside_realtime_tick_get_agent = False
            self._tick_called_in_get_agent = False
            self._quote_anchor_called_in_get_agent = False
            self._provider_error_in_get_agent = None

    # 抓取数据函数, 实现单次证券的抓取逻辑即可
    def ts2db_get_data(self):
        if (
            getattr(
                self,
                '_inside_realtime_tick_get_agent',
                False,
            )
            and (
                getattr(
                    self,
                    '_tick_called_in_get_agent',
                    False,
                )
                or getattr(
                    self,
                    '_quote_anchor_called_in_get_agent',
                    False,
                )
            )
        ):
            provider_error = getattr(
                self,
                '_provider_error_in_get_agent',
                None,
            )
            if provider_error is not None:
                raise provider_error
            raise RealtimeTickDateUnverifiedError(
                'realtime_tick provider was already called '
                'for this fetch'
            )
        try:
            return self._ts2db_get_data_once()
        except Exception as provider_error:
            if (
                getattr(
                    self,
                    '_inside_realtime_tick_get_agent',
                    False,
                )
                and (
                    getattr(
                        self,
                        '_tick_called_in_get_agent',
                        False,
                    )
                    or getattr(
                        self,
                        '_quote_anchor_called_in_get_agent',
                        False,
                    )
                )
            ):
                self._provider_error_in_get_agent = provider_error
            raise

    def _ts2db_get_data_once(self):
        self._clear_realtime_tick_date_verification()
        code = _canonical_code(self.params.code, 'requested code')
        source = self.params.src
        if type(source) is not str or source != 'dc':
            raise RealtimeTickDateUnverifiedError(
                'realtime_tick source must be exactly dc'
            )
        quote_api = getattr(self.params.ts, 'realtime_quote', None)
        if not callable(quote_api):
            raise RealtimeTickDateUnverifiedError(
                'realtime_tick quote anchor API is unavailable'
            )

        tick_started_at = _read_shanghai_clock()
        self.realtime_tick_call_started_at = tick_started_at
        if getattr(
            self,
            '_inside_realtime_tick_get_agent',
            False,
        ):
            self._tick_called_in_get_agent = True
        try:
            frame = self.params.ts_api(ts_code=code, src=source)
        finally:
            tick_ended_at = _read_shanghai_clock()
            self.realtime_tick_call_ended_at = tick_ended_at

        _require_one_continuous_session(
            tick_started_at,
            tick_ended_at,
        )
        max_tick_time = _max_tick_time(frame)

        quote_started_at = _read_shanghai_clock()
        self.realtime_quote_anchor_started_at = quote_started_at
        if getattr(
            self,
            '_inside_realtime_tick_get_agent',
            False,
        ):
            self._quote_anchor_called_in_get_agent = True
        try:
            quote_frame = quote_api(ts_code=code, src=source)
        finally:
            quote_ended_at = _read_shanghai_clock()
            self.realtime_quote_anchor_ended_at = quote_ended_at

        _require_one_continuous_session(
            tick_started_at,
            tick_ended_at,
            quote_started_at,
            quote_ended_at,
        )
        provider_date, quote_time = _quote_anchor_values(
            quote_frame,
            code,
            source,
        )
        invocation_date = tick_started_at.strftime('%Y%m%d')
        if provider_date != invocation_date:
            raise RealtimeTickDateUnverifiedError(
                'realtime_tick quote provider date does not match '
                'the invocation local date'
            )
        _fresh_event_datetime(
            provider_date,
            max_tick_time,
            tick_ended_at,
            'maximum tick time',
        )
        _fresh_event_datetime(
            provider_date,
            quote_time,
            quote_ended_at,
            'quote time',
        )
        identity_counter = _tick_identity_counter(
            frame,
            provider_date,
            code,
            source,
        )

        self._verified_tick_frame_id = id(frame)
        self._verified_tick_provider_date = provider_date
        self._verified_tick_code = code
        self._verified_tick_source = source
        self._verified_tick_max_time = max_tick_time
        self._verified_tick_identity_counter = identity_counter
        return frame

    def _cleanup_written_dates_after_failure(
        self,
        original_error,
        successful_write_count_before,
    ):
        if (
            not getattr(self, '_provider_trade_dates', None)
            or getattr(self, '_successful_tick_write_count', 0)
            <= successful_write_count_before
        ):
            return None
        keys = getattr(
            self.params,
            'deal_data__duplicate_data_key',
            None,
        )
        try:
            return self.ts2db_deal_duplicate_datas(keys)
        except Exception as cleanup_error:
            note = (
                'realtime_tick date-scoped cleanup after failure also '
                f'failed ({type(cleanup_error).__name__})'
            )
            try:
                original_error.add_note(note)
            except Exception:
                pass
            try:
                logging.error(note)
            except Exception:
                pass
            return None

    def _run(self):
        i_times = 0
        run_date = None
        successful_write_count_before = getattr(
            self,
            '_successful_tick_write_count',
            0,
        )
        try:
            while True:
                loop_clock = _read_shanghai_clock()
                local_date = loop_clock.date()
                if run_date is None:
                    run_date = local_date
                elif local_date != run_date:
                    self.params.code = ''
                    return i_times

                session_index = _continuous_session_index(loop_clock)
                if session_index is None:
                    if (
                        loop_clock.time()
                        > CN_CONTINUOUS_SESSION_WINDOWS[-1][1]
                    ):
                        self.params.code = ''
                        return i_times
                    self.ts2db_rt__gap_sleep()
                    continue

                completed_code = False
                for code_str in self._iter_code_batches():
                    call_clock = _read_shanghai_clock()
                    if (
                        call_clock.date() != run_date
                        or _continuous_session_index(call_clock)
                        != session_index
                    ):
                        break
                    self.params.code = code_str
                    self.ts2db_get_data_agent()
                    self.ts2db_clean_data_agent()
                    self.ts2db_rt__get_add_data()
                    self.ts2db_write_db_agent()
                    completed_code = True
                self.params.code = ''
                if completed_code:
                    i_times += 1
                self.ts2db_rt__gap_sleep()
        except Exception as original_error:
            self.params.code = ''
            self._cleanup_written_dates_after_failure(
                original_error,
                successful_write_count_before,
            )
            raise

    # 每只证券抓取后，实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        try:
            provider_date, _code, _source = (
                self._verified_context_for_write()
            )
            result = self.df.to_sql(
                self.params.table_name,
                self.params.db_engine,
                chunksize=1000000,
                if_exists='append',
                index=False,
                dtype={'trade_date': DATE,
                       'time': TIME,
                       'ts_code': NVARCHAR(20),
                       'src': NVARCHAR(10),
                       'type': NVARCHAR(5),
                       'price': DECIMAL(25, 4),
                       'change': DECIMAL(25, 4),
                       'volume': DECIMAL(25, 4),
                       'amount': DECIMAL(25, 4)},
            )
            self._provider_trade_dates.add(provider_date)
            self._successful_tick_write_count += 1
            return result
        finally:
            self._clear_realtime_tick_date_verification()

    def ts2db_clean_data(self):
        provider_date, code, source = self._verified_context_for_clean()
        self._verified_tick_cleaned = False
        if 'TIME' in self.df.columns:
            self.df.rename(columns={'TIME': 'time'}, inplace=True)
        elif 'trade_time' in self.df.columns:
            self.df.rename(columns={'trade_time': 'time'}, inplace=True)
        self.df.rename(columns={'PRICE': 'price',
                                'CHANGE': 'change',
                                'TYPE': 'type',
                                'VOLUME': 'volume',
                                'AMOUNT': 'amount'}, inplace=True)
        self.df['ts_code'] = code
        self.df['trade_date'] = provider_date
        self.df['src'] = source
        cleaned_identities = _tick_identity_counter(
            self.df,
            provider_date,
            code,
            source,
            canonical_columns=True,
        )
        if cleaned_identities != self._verified_tick_identity_counter:
            raise RealtimeTickDateUnverifiedError(
                'realtime_tick cleaner changed the verified identity'
            )
        self._verified_tick_cleaned = True

    def ts2db_deal_duplicate_datas(self, keys):
        if keys is None:
            return None
        provider_trade_dates = getattr(
            self,
            '_provider_trade_dates',
            None,
        )
        if provider_trade_dates is None:
            raise RealtimeTickDateUnverifiedError(
                'realtime_tick provider trade-date scope is not initialized'
            )
        if not provider_trade_dates:
            return None
        if not getattr(
            self.params,
            'deal_duplicate_strict_date_scope',
            False,
        ):
            raise RealtimeTickDateUnverifiedError(
                'realtime_tick strict date-scoped cleanup is required'
            )
        pending_dates = tuple(sorted(provider_trade_dates))
        str_date = self.params.str_date
        end_date = self.params.end_date
        try:
            result = None
            for provider_date in pending_dates:
                if _canonical_provider_date(provider_date) != provider_date:
                    raise RealtimeTickDateUnverifiedError(
                        'realtime_tick cleanup date is not canonical'
                    )
                self.params.str_date = provider_date
                self.params.end_date = provider_date
                result = super().ts2db_deal_duplicate_datas(keys)
            return result
        finally:
            self.params.str_date = str_date
            self.params.end_date = end_date


if __name__ == '__main__':
    params = _params()
    params.codelist = pd.DataFrame({'ts_code': ['000001.SZ', '000002.SZ', '000003.SZ']})
    get_rt_stk_tick__east(params).run()

    # end_str = input("加载完毕，请复核是否正确执行！")
