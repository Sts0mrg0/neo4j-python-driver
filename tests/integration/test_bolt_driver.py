#!/usr/bin/env python
# -*- encoding: utf-8 -*-

# Copyright (c) 2002-2020 "Neo4j,"
# Neo4j Sweden AB [http://neo4j.com]
#
# This file is part of Neo4j.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import pytest
from pytest import fixture

from neo4j import (
    GraphDatabase,
    BoltDriver,
    Version,
    READ_ACCESS,
    WRITE_ACCESS,
    ResultSummary,
    unit_of_work,
    Transaction,
    Result,
    ServerInfo,
)
from neo4j.exceptions import (
    ServiceUnavailable,
    AuthError,
    ConfigurationError,
    ClientError,
)
from neo4j._exceptions import BoltHandshakeError
from neo4j.io._bolt3 import Bolt3

# python -m pytest tests/integration/test_bolt_driver.py -s -v


def test_bolt_uri(bolt_uri, auth):
    # python -m pytest tests/integration/test_bolt_driver.py -s -v -k test_bolt_uri
    try:
        with GraphDatabase.driver(bolt_uri, auth=auth) as driver:
            with driver.session() as session:
                value = session.run("RETURN 1").single().value()
                assert value == 1
    except ServiceUnavailable as error:
        assert isinstance(error.__cause__, BoltHandshakeError)
        pytest.skip(error.args[0])


# def test_readonly_bolt_uri(readonly_bolt_uri, auth):
#     with GraphDatabase.driver(readonly_bolt_uri, auth=auth) as driver:
#         with driver.session() as session:
#             value = session.run("RETURN 1").single().value()
#             assert value == 1


def test_normal_use_case(bolt_driver):
    # python -m pytest tests/integration/test_bolt_driver.py -s -v -k test_normal_use_case
    session = bolt_driver.session()
    value = session.run("RETURN 1").single().value()
    assert value == 1


def test_invalid_url_scheme(service):
    # python -m pytest tests/integration/test_bolt_driver.py -s -v -k test_invalid_url_scheme
    address = service.addresses[0]
    uri = "x://{}:{}".format(address[0], address[1])
    try:
        with pytest.raises(ConfigurationError):
            _ = GraphDatabase.driver(uri, auth=service.auth)
    except ServiceUnavailable as error:
        if isinstance(error.__cause__, BoltHandshakeError):
            pytest.skip(error.args[0])


def test_fail_nicely_when_using_http_port(service):
    # python -m pytest tests/integration/test_bolt_driver.py -s -v -k test_fail_nicely_when_using_http_port
    from tests.integration.conftest import NEO4J_PORTS
    address = service.addresses[0]
    uri = "bolt://{}:{}".format(address[0], NEO4J_PORTS["http"])
    with pytest.raises(ServiceUnavailable):
        _ = GraphDatabase.driver(uri, auth=service.auth)


def test_custom_resolver(service):
    # python -m pytest tests/integration/test_bolt_driver.py -s -v -k test_custom_resolver
    _, port = service.addresses[0]

    def my_resolver(socket_address):
        assert socket_address == ("*", 7687)
        yield "99.99.99.99", port     # should be rejected as unable to connect
        yield "127.0.0.1", port       # should succeed

    try:
        with GraphDatabase.driver("bolt://*", auth=service.auth,
                                  connection_timeout=3,  # enables rapid timeout
                                  resolver=my_resolver) as driver:
            with driver.session() as session:
                summary = session.run("RETURN 1").consume()
                assert summary.server.address == ("127.0.0.1", port)
    except ServiceUnavailable as error:
        if isinstance(error.__cause__, BoltHandshakeError):
            pytest.skip(error.args[0])


def test_encrypted_set_to_false_by_default(bolt_driver):
    # python -m pytest tests/integration/test_bolt_driver.py -s -v -k test_encrypted_set_to_false_by_default
    assert bolt_driver.encrypted is False


def test_should_fail_on_incorrect_password(bolt_uri):
    # python -m pytest tests/integration/test_bolt_driver.py -s -v -k test_should_fail_on_incorrect_password
    with pytest.raises(AuthError):
        try:
            with GraphDatabase.driver(bolt_uri, auth=("neo4j", "wrong-password")) as driver:
                with driver.session() as session:
                    _ = session.run("RETURN 1")
        except ServiceUnavailable as error:
            if isinstance(error.__cause__, BoltHandshakeError):
                pytest.skip(error.args[0])


def test_supports_multi_db(bolt_uri, auth):
    # python -m pytest tests/integration/test_bolt_driver.py -s -v -k test_supports_multi_db
    try:
        driver = GraphDatabase.driver(bolt_uri, auth=auth)
        assert isinstance(driver, BoltDriver)
    except ServiceUnavailable as error:
        if isinstance(error.__cause__, BoltHandshakeError):
            pytest.skip(error.args[0])

    with driver.session() as session:
        result = session.run("RETURN 1")
        _ = result.single().value()  # Consumes the result
        summary = result.consume()
        server_info = summary.server

    assert isinstance(summary, ResultSummary)
    assert isinstance(server_info, ServerInfo)
    assert server_info.version_info() is not None
    assert isinstance(server_info.protocol_version, Version)

    result = driver.supports_multi_db()
    driver.close()

    if server_info.protocol_version == Bolt3.PROTOCOL_VERSION:
        assert result is False
        assert summary.database is None
        assert summary.query_type == "r"
    else:
        assert result is True
        assert server_info.version_info() >= Version(4, 0)
        assert server_info.protocol_version >= Version(4, 0)
        assert summary.database == "neo4j"  # This is the default database name if not set explicitly on the Neo4j Server
        assert summary.query_type == "r"


def test_test_multi_db_specify_database(bolt_uri, auth):
    # python -m pytest tests/integration/test_bolt_driver.py -s -v -k test_test_multi_db_specify_database
    try:
        with GraphDatabase.driver(bolt_uri, auth=auth, database="test_database") as driver:
            with driver.session() as session:
                result = session.run("RETURN 1")
                result_iter = iter(result)
                assert next(result_iter) == 1
                summary = result.consume()
                assert summary.database == "test_database"
    except ServiceUnavailable as error:
        if isinstance(error.__cause__, BoltHandshakeError):
            pytest.skip(error.args[0])
    except ConfigurationError as error:
        assert "Database name parameter for selecting database is not supported in Bolt Protocol Version(3, 0)" in error.args[0]
    except ClientError as error:
        # FAILURE {'code': 'Neo.ClientError.Database.DatabaseNotFound' - This message is sent from the server
        assert error.args[0] == "Database does not exist. Database name: 'test_database'."


def test_bolt_driver_fetch_size_config_case_on_close_result_consume(bolt_uri, auth):
    # python -m pytest tests/integration/test_bolt_driver.py -s -v -k test_bolt_driver_fetch_size_config_case_on_close_result_consume
    try:
        with GraphDatabase.driver(bolt_uri, auth=auth, user_agent="test") as driver:
            assert isinstance(driver, BoltDriver)
            with driver.session(fetch_size=2, default_access_mode=READ_ACCESS) as session:
                result = session.run("UNWIND [1,2,3,4] AS x RETURN x")
                # Check the expected result with logging manually
    except ServiceUnavailable as error:
        if isinstance(error.__cause__, BoltHandshakeError):
            pytest.skip(error.args[0])


def test_bolt_driver_fetch_size_config_case_normal(bolt_uri, auth):
    # python -m pytest tests/integration/test_bolt_driver.py -s -v -k test_bolt_driver_fetch_size_config_case_normal
    try:
        with GraphDatabase.driver(bolt_uri, auth=auth, user_agent="test") as driver:
            assert isinstance(driver, BoltDriver)
            with driver.session(fetch_size=2, default_access_mode=READ_ACCESS) as session:
                expected = []
                result = session.run("UNWIND [1,2,3,4] AS x RETURN x")
                for record in result:
                    expected.append(record["x"])

        assert expected == [1, 2, 3, 4]
    except ServiceUnavailable as error:
        if isinstance(error.__cause__, BoltHandshakeError):
            pytest.skip(error.args[0])


def test_bolt_driver_fetch_size_config_run_consume_run(bolt_uri, auth):
    # python -m pytest tests/integration/test_bolt_driver.py -s -v -k test_bolt_driver_fetch_size_config_run_consume_run
    try:
        with GraphDatabase.driver(bolt_uri, auth=auth, user_agent="test") as driver:
            assert isinstance(driver, BoltDriver)
            with driver.session(fetch_size=2, default_access_mode=READ_ACCESS) as session:
                expected = []
                result1 = session.run("UNWIND [1,2,3,4] AS x RETURN x")
                result1.consume()
                result2 = session.run("UNWIND [5,6,7,8] AS x RETURN x")

                for record in result2:
                    expected.append(record["x"])

                result_summary = result2.consume()
                assert isinstance(result_summary, ResultSummary)

        assert expected == [5, 6, 7, 8]
    except ServiceUnavailable as error:
        if isinstance(error.__cause__, BoltHandshakeError):
            pytest.skip(error.args[0])


def test_bolt_driver_fetch_size_config_run_run(bolt_uri, auth):
    # python -m pytest tests/integration/test_bolt_driver.py -s -v -k test_bolt_driver_fetch_size_config_run_run
    try:
        with GraphDatabase.driver(bolt_uri, auth=auth, user_agent="test") as driver:
            assert isinstance(driver, BoltDriver)
            with driver.session(fetch_size=2, default_access_mode=READ_ACCESS) as session:
                expected = []
                result1 = session.run("UNWIND [1,2,3,4] AS x RETURN x")
                result2 = session.run("UNWIND [5,6,7,8] AS x RETURN x")

                for record in result2:
                    expected.append(record["x"])

                result_summary = result2.consume()
                assert isinstance(result_summary, ResultSummary)

        assert expected == [5, 6, 7, 8]
    except ServiceUnavailable as error:
        if isinstance(error.__cause__, BoltHandshakeError):
            pytest.skip(error.args[0])


def test_bolt_driver_read_transaction_fetch_size_config_normal_case(bolt_uri, auth):
    # python -m pytest tests/integration/test_bolt_driver.py -s -v -k test_bolt_driver_read_transaction_fetch_size_config_normal_case
    @unit_of_work(timeout=3, metadata={"foo": "bar"})
    def unwind(transaction):
        assert isinstance(transaction, Transaction)
        values = []
        result = transaction.run("UNWIND [1,2,3,4] AS x RETURN x")
        assert isinstance(result, Result)
        for record in result:
            values.append(record["x"])
        return values

    try:
        with GraphDatabase.driver(bolt_uri, auth=auth, user_agent="test") as driver:
            assert isinstance(driver, BoltDriver)
            with driver.session(fetch_size=2, default_access_mode=READ_ACCESS) as session:
                expected = session.read_transaction(unwind)

        assert expected == [1, 2, 3, 4]
    except ServiceUnavailable as error:
        if isinstance(error.__cause__, BoltHandshakeError):
            pytest.skip(error.args[0])


def test_bolt_driver_multiple_results_case_1(bolt_uri, auth):
    # python -m pytest tests/integration/test_bolt_driver.py -s -v -k test_bolt_driver_multiple_results_case_1
    try:
        with GraphDatabase.driver(bolt_uri, auth=auth, user_agent="test") as driver:
            assert isinstance(driver, BoltDriver)
            with driver.session(fetch_size=2, default_access_mode=READ_ACCESS) as session:
                transaction = session.begin_transaction(timeout=3, metadata={"foo": "bar"})
                result1 = transaction.run("UNWIND [1,2,3,4] AS x RETURN x")
                values1 = []
                for ix in result1:
                    values1.append(ix["x"])
                transaction.commit()
                assert values1 == [1, 2, 3, 4]

    except ServiceUnavailable as error:
        if isinstance(error.__cause__, BoltHandshakeError):
            pytest.skip(error.args[0])


def test_bolt_driver_multiple_results_case_2(bolt_uri, auth):
    # python -m pytest tests/integration/test_bolt_driver.py -s -v -k test_bolt_driver_multiple_results_case_2
    try:
        with GraphDatabase.driver(bolt_uri, auth=auth, user_agent="test") as driver:
            assert isinstance(driver, BoltDriver)
            with driver.session(fetch_size=2, default_access_mode=READ_ACCESS) as session:
                transaction = session.begin_transaction(timeout=3, metadata={"foo": "bar"})
                result1 = transaction.run("UNWIND [1,2,3,4] AS x RETURN x")
                result2 = transaction.run("UNWIND [5,6,7,8] AS x RETURN x")
                values1 = []
                values2 = []
                for ix in result2:
                    values2.append(ix["x"])
                for ix in result1:
                    values1.append(ix["x"])
                transaction.commit()
                assert values2 == [5, 6, 7, 8]
                assert values1 == [1, 2, 3, 4]

    except ServiceUnavailable as error:
        if isinstance(error.__cause__, BoltHandshakeError):
            pytest.skip(error.args[0])


def test_bolt_driver_multiple_results_case_3(bolt_uri, auth):
    # python -m pytest tests/integration/test_bolt_driver.py -s -v -k test_bolt_driver_multiple_results_case_3
    try:
        with GraphDatabase.driver(bolt_uri, auth=auth, user_agent="test") as driver:
            assert isinstance(driver, BoltDriver)
            with driver.session(fetch_size=2, default_access_mode=READ_ACCESS) as session:
                transaction = session.begin_transaction(timeout=3, metadata={"foo": "bar"})
                values1 = []
                values2 = []
                result1 = transaction.run("UNWIND [1,2,3,4] AS x RETURN x")
                result1_iter = iter(result1)
                values1.append(next(result1_iter)["x"])
                result2 = transaction.run("UNWIND [5,6,7,8] AS x RETURN x")
                for ix in result2:
                    values2.append(ix["x"])
                transaction.commit()  # Should discard the rest of records in result1 and result2 -> then set mode discard.
                assert values2 == [5, 6, 7, 8]
                assert result2._closed is True
                assert values1 == [1, ]

                try:
                    values1.append(next(result1_iter)["x"])
                except StopIteration as e:
                    # Bolt 4.0
                    assert values1 == [1, ]
                    assert result1._closed is True
                else:
                    # Bolt 3 only have PULL ALL and no qid so it will behave like autocommit r1=session.run rs2=session.run
                    values1.append(next(result1_iter)["x"])
                    assert values1 == [1, 2, 3]
                    assert result1._closed is False

        assert result1._closed is True

    except ServiceUnavailable as error:
        if isinstance(error.__cause__, BoltHandshakeError):
            pytest.skip(error.args[0])


def test_bolt_driver_case_pull_no_records(driver):
    # python -m pytest tests/integration/test_bolt_driver.py -s -v -k test_bolt_driver_case_pull_no_records
    try:
        with driver.session(default_access_mode=WRITE_ACCESS) as session:
            with session.begin_transaction() as tx:
                result = tx.run("CREATE (a:Thing {uuid:$uuid})", uuid=123)
    except ServiceUnavailable as error:
        if isinstance(error.__cause__, BoltHandshakeError):
            pytest.skip(error.args[0])


@fixture
def server_info(driver):
    """ Simple fixture to provide quick and easy access to a
    :class:`.ServerInfo` object.
    """
    with driver.session() as session:
        summary = session.run("RETURN 1").consume()
        yield summary.server


def test_server_address(server_info):
    assert server_info.address == ("127.0.0.1", 7687)


def test_server_protocol_version(server_info):
    assert server_info.protocol_version >= (3, 0)


def test_server_agent(server_info):
    assert server_info.agent.startswith("Neo4j/")


def test_server_connection_id(server_info):
    cid = server_info.connection_id
    assert cid.startswith("bolt-") and cid[5:].isdigit()
