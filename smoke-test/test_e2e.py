import time

import pytest
import requests
import urllib
from datahub.cli.docker import check_local_docker_containers
from datahub.ingestion.run.pipeline import Pipeline

GMS_ENDPOINT = "http://localhost:8080"
FRONTEND_ENDPOINT = "http://localhost:9002"
KAFKA_BROKER = "localhost:9092"

bootstrap_sample_data = "../metadata-ingestion/examples/mce_files/bootstrap_mce.json"
usage_sample_data = (
    "../metadata-ingestion/tests/integration/bigquery-usage/bigquery_usages_golden.json"
)
bq_sample_data = "./sample_bq_data.json"
restli_default_headers = {
    "X-RestLi-Protocol-Version": "2.0.0",
}
kafka_post_ingestion_wait_sec = 60


@pytest.fixture(scope="session")
def wait_for_healthchecks():
    # Simply assert that everything is healthy, but don't wait.
    assert not check_local_docker_containers()
    yield


@pytest.mark.dependency()
def test_healthchecks(wait_for_healthchecks):
    # Call to wait_for_healthchecks fixture will do the actual functionality.
    pass


def ingest_file(filename: str):
    pipeline = Pipeline.create(
        {
            "source": {
                "type": "file",
                "config": {"filename": filename},
            },
            "sink": {
                "type": "datahub-rest",
                "config": {"server": GMS_ENDPOINT},
            },
        }
    )
    pipeline.run()
    pipeline.raise_from_status()


@pytest.mark.dependency(depends=["test_healthchecks"])
def test_ingestion_via_rest(wait_for_healthchecks):
    ingest_file(bootstrap_sample_data)


@pytest.mark.dependency(depends=["test_healthchecks"])
def test_ingestion_usage_via_rest(wait_for_healthchecks):
    ingest_file(usage_sample_data)


@pytest.mark.dependency(depends=["test_healthchecks"])
def test_ingestion_via_kafka(wait_for_healthchecks):
    pipeline = Pipeline.create(
        {
            "source": {
                "type": "file",
                "config": {"filename": bq_sample_data},
            },
            "sink": {
                "type": "datahub-kafka",
                "config": {
                    "connection": {
                        "bootstrap": KAFKA_BROKER,
                    }
                },
            },
        }
    )
    pipeline.run()
    pipeline.raise_from_status()

    # Since Kafka emission is asynchronous, we must wait a little bit so that
    # the changes are actually processed.
    time.sleep(kafka_post_ingestion_wait_sec)


@pytest.mark.dependency(
    depends=[
        "test_ingestion_via_rest",
        "test_ingestion_via_kafka",
        "test_ingestion_usage_via_rest",
    ]
)
def test_run_ingestion(wait_for_healthchecks):
    # Dummy test so that future ones can just depend on this one.
    pass


@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion"])
def test_gms_get_user():
    username = "jdoe"
    urn = f"urn:li:corpuser:{username}"
    response = requests.get(
        f"{GMS_ENDPOINT}/entities/{urllib.parse.quote(urn)}",
        headers={
            **restli_default_headers,
        },
    )
    response.raise_for_status()
    data = response.json()

    assert data["value"]
    assert data["value"]["com.linkedin.metadata.snapshot.CorpUserSnapshot"]
    assert data["value"]["com.linkedin.metadata.snapshot.CorpUserSnapshot"]["urn"] == urn


@pytest.mark.parametrize(
    "platform,dataset_name,env",
    [
        (
            # This one tests the bootstrap sample data.
            "urn:li:dataPlatform:kafka",
            "SampleKafkaDataset",
            "PROD",
        ),
        (
            # This one tests BigQuery ingestion.
            "urn:li:dataPlatform:bigquery",
            "bigquery-public-data.covid19_geotab_mobility_impact.us_border_wait_times",
            "PROD",
        ),
    ],
)
@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion"])
def test_gms_get_dataset(platform, dataset_name, env):
    platform = "urn:li:dataPlatform:bigquery"
    dataset_name = (
        "bigquery-public-data.covid19_geotab_mobility_impact.us_border_wait_times"
    )
    env = "PROD"
    urn = f"urn:li:dataset:({platform},{dataset_name},{env})"

    response = requests.get(
        f"{GMS_ENDPOINT}/entities/{urllib.parse.quote(urn)}",
        headers={
            **restli_default_headers,
            "X-RestLi-Method": "get",
        },
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data["value"]
    assert res_data["value"]["com.linkedin.metadata.snapshot.DatasetSnapshot"]
    assert res_data["value"]["com.linkedin.metadata.snapshot.DatasetSnapshot"]["urn"] == urn


@pytest.mark.parametrize(
    "query,min_expected_results",
    [
        ("covid", 1),
        ("sample", 3),
    ],
)
@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion"])
def test_gms_search_dataset(query, min_expected_results):


    json = {
            "input": f"{query}",
            "entity": "dataset",
            "start": 0,
            "count": 10
    }
    print(json)
    response = requests.post(
        f"{GMS_ENDPOINT}/entities?action=search",
        headers=restli_default_headers,
        json=json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data["value"]
    assert res_data["value"]["numEntities"] >= min_expected_results
    assert len(res_data["value"]["entities"]) >= min_expected_results


@pytest.mark.parametrize(
    "query,min_expected_results",
    [
        ("covid", 1),
        ("sample", 3),
    ],
)
@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion"])
def test_gms_search_across_entities(query, min_expected_results):

    json = {
            "input": f"{query}",
            "entities": [],
            "start": 0,
            "count": 10
    }
    print(json)
    response = requests.post(
        f"{GMS_ENDPOINT}/entities?action=searchAcrossEntities",
        headers=restli_default_headers,
        json=json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data["value"]
    assert res_data["value"]["numEntities"] >= min_expected_results
    assert len(res_data["value"]["entities"]) >= min_expected_results


@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion"])
def test_gms_usage_fetch():
    response = requests.post(
        f"{GMS_ENDPOINT}/usageStats?action=queryRange",
        headers=restli_default_headers,
        json={
            "resource": "urn:li:dataset:(urn:li:dataPlatform:bigquery,harshal-playground-306419.test_schema.excess_deaths_derived,PROD)",
            "duration": "DAY",
            "rangeFromEnd": "ALL",
        },
    )
    response.raise_for_status()

    data = response.json()["value"]

    assert len(data["buckets"]) == 6
    assert data["buckets"][0]["metrics"]["topSqlQueries"]

    fields = data["aggregations"].pop("fields")
    assert len(fields) == 12
    assert fields[0]["count"] == 7

    users = data["aggregations"].pop("users")
    assert len(users) == 1
    assert users[0]["count"] == 7

    assert data["aggregations"] == {
        # "fields" and "users" already popped out
        "totalSqlQueries": 7,
        "uniqueUserCount": 1,
    }


@pytest.fixture(scope="session")
def frontend_session(wait_for_healthchecks):
    session = requests.Session()

    headers = {
        "Content-Type": "application/json",
    }
    data = '{"username":"datahub", "password":"datahub"}'
    response = session.post(
        f"{FRONTEND_ENDPOINT}/logIn", headers=headers, data=data
    )
    response.raise_for_status()

    yield session


@pytest.mark.dependency(depends=["test_healthchecks"])
def test_frontend_auth(frontend_session):
    pass


@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion"])
def test_frontend_browse_datasets(frontend_session):

    json = {
        "query": """query browse($input: BrowseInput!) {\n
                        browse(input: $input) {\n
                            start\n
                            count\n
                            total\n
                            groups {
                                name
                            }
                            entities {\n
                                ... on Dataset {\n
                                    urn\n
                                    name\n
                                }\n
                            }\n
                        }\n
                    }""",
        "variables": {
            "input": {
                "type": "DATASET",
                "path": ["prod"]
            }
        }
    }

    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )

    response.raise_for_status()
    res_data = response.json()
    assert res_data
    assert res_data["data"]
    assert res_data["data"]["browse"]
    assert len(res_data["data"]["browse"]["entities"]) == 0
    assert len(res_data["data"]["browse"]["groups"]) > 0


@pytest.mark.parametrize(
    "query,min_expected_results",
    [
        ("covid", 1),
        ("sample", 3),
    ],
)
@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion"])
def test_frontend_search_datasets(frontend_session, query, min_expected_results):

    json = {
        "query": """query search($input: SearchInput!) {\n
            search(input: $input) {\n
                start\n
                count\n
                total\n 
                searchResults {\n
                    entity {\n
                        ... on Dataset {\n
                            urn\n
                            name\n
                        }\n
                    }\n
                }\n
            }\n
        }""",
        "variables": {
            "input": {
                "type": "DATASET",
                "query": f"{query}",
                "start": 0,
                "count": 10
            }
        }
    }

    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["search"]
    assert res_data["data"]["search"]["total"] >= min_expected_results
    assert len(res_data["data"]["search"]["searchResults"]) >= min_expected_results


@pytest.mark.parametrize(
    "query,min_expected_results",
    [
        ("covid", 1),
        ("sample", 3),
    ],
)
@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion"])
def test_frontend_search_across_entities(frontend_session, query, min_expected_results):

    json = {
        "query": """query searchAcrossEntities($input: SearchAcrossEntitiesInput!) {\n
            searchAcrossEntities(input: $input) {\n
                start\n
                count\n
                total\n 
                searchResults {\n
                    entity {\n
                        ... on Dataset {\n
                            urn\n
                            name\n
                        }\n
                    }\n
                }\n
            }\n
        }""",
        "variables": {
            "input": {
                "types": [],
                "query": f"{query}",
                "start": 0,
                "count": 10
            }
        }
    }

    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["searchAcrossEntities"]
    assert res_data["data"]["searchAcrossEntities"]["total"] >= min_expected_results
    assert len(res_data["data"]["searchAcrossEntities"]["searchResults"]) >= min_expected_results


@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion"])
def test_frontend_user_info(frontend_session):

    urn = f"urn:li:corpuser:datahub"
    json = {
        "query": """query corpUser($urn: String!) {\n
            corpUser(urn: $urn) {\n
                urn\n
                username\n
                editableInfo {\n
                    pictureLink\n
                }\n
                info {\n
                    firstName\n
                    fullName\n
                    title\n
                    email\n
                }\n
            }\n
        }""",
        "variables": {
            "urn": urn
        }
    }
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data 
    assert res_data["data"]
    assert res_data["data"]["corpUser"]
    assert res_data["data"]["corpUser"]["urn"] == urn


@pytest.mark.parametrize(
    "platform,dataset_name,env",
    [
        (
            # This one tests the bootstrap sample data.
            "urn:li:dataPlatform:kafka",
            "SampleKafkaDataset",
            "PROD",
        ),
        (
            # This one tests BigQuery ingestion.
            "urn:li:dataPlatform:bigquery",
            "bigquery-public-data.covid19_geotab_mobility_impact.us_border_wait_times",
            "PROD",
        ),
    ],
)
@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion"])
def test_frontend_datasets(frontend_session, platform, dataset_name, env):
    urn = f"urn:li:dataset:({platform},{dataset_name},{env})"
    json = {
        "query": """query getDataset($urn: String!) {\n
            dataset(urn: $urn) {\n
                urn\n
                name\n
                description\n
                platform {\n
                    urn\n
                }\n
                schemaMetadata {\n
                    name\n
                    version\n
                    createdAt\n
                }\n
            }\n
        }""",
        "variables": {
            "urn": urn
        }
    }
    # Basic dataset info.
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["dataset"]
    assert res_data["data"]["dataset"]["urn"] == urn
    assert res_data["data"]["dataset"]["name"] == dataset_name
    assert res_data["data"]["dataset"]["platform"]["urn"] == platform

@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion"])
def test_ingest_with_system_metadata():
    response = requests.post(
        f"{GMS_ENDPOINT}/entities?action=ingest",
        headers=restli_default_headers,
        json={
          'entity':
            {
              'value':
                {'com.linkedin.metadata.snapshot.CorpUserSnapshot':
                  {'urn': 'urn:li:corpuser:datahub', 'aspects':
                    [{'com.linkedin.identity.CorpUserInfo': {'active': True, 'displayName': 'Data Hub', 'email': 'datahub@linkedin.com', 'title': 'CEO', 'fullName': 'Data Hub'}}]
                   }
                  }
                },
              'systemMetadata': {'lastObserved': 1628097379571, 'runId': 'af0fe6e4-f547-11eb-81b2-acde48001122'}
        },
    )
    response.raise_for_status()

@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion"])
def test_ingest_with_blank_system_metadata():
    response = requests.post(
        f"{GMS_ENDPOINT}/entities?action=ingest",
        headers=restli_default_headers,
        json={
          'entity':
            {
              'value':
                {'com.linkedin.metadata.snapshot.CorpUserSnapshot':
                  {'urn': 'urn:li:corpuser:datahub', 'aspects':
                    [{'com.linkedin.identity.CorpUserInfo': {'active': True, 'displayName': 'Data Hub', 'email': 'datahub@linkedin.com', 'title': 'CEO', 'fullName': 'Data Hub'}}]
                   }
                  }
                },
              'systemMetadata': {}
        },
    )
    response.raise_for_status()

@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion"])
def test_ingest_without_system_metadata():
    response = requests.post(
        f"{GMS_ENDPOINT}/entities?action=ingest",
        headers=restli_default_headers,
        json={
          'entity':
            {
              'value':
                {'com.linkedin.metadata.snapshot.CorpUserSnapshot':
                  {'urn': 'urn:li:corpuser:datahub', 'aspects':
                    [{'com.linkedin.identity.CorpUserInfo': {'active': True, 'displayName': 'Data Hub', 'email': 'datahub@linkedin.com', 'title': 'CEO', 'fullName': 'Data Hub'}}]
                   }
                  }
             },
        },
    )
    response.raise_for_status()


@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion"])
def test_frontend_list_policies(frontend_session):

    json = {
        "query": """query listPolicies($input: ListPoliciesInput!) {\n
            listPolicies(input: $input) {\n
                start\n
                count\n
                total\n
                policies {\n
                    urn\n
                    type\n
                    name\n
                    description\n
                    state\n
                    resources {\n
                      type\n
                      allResources\n
                      resources\n
                    }\n
                    privileges\n
                    actors {\n
                      users\n
                      groups\n
                      allUsers\n
                      allGroups\n
                      resourceOwners\n
                    }\n
                    editable\n
                }\n
            }\n
        }""",
        "variables": {
            "input": {
              "start": "0",
              "count": "20",
            }
        }
    }
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["listPolicies"]
    assert res_data["data"]["listPolicies"]["start"] is 0
    assert res_data["data"]["listPolicies"]["count"] is 8
    assert len(res_data["data"]["listPolicies"]["policies"]) is 8 # Length of default policies.

@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion", "test_frontend_list_policies"])
def test_frontend_update_policy(frontend_session):

    json = {
        "query": """mutation updatePolicy($urn: String!, $input: PolicyUpdateInput!) {\n
            updatePolicy(urn: $urn, input: $input) }""",
        "variables": {
            "urn": "urn:li:dataHubPolicy:7",
            "input": {
                "type": "PLATFORM",
                "state": "INACTIVE",
                "name": "Updated Platform Policy",
                "description": "My Metadaata Policy",
                "privileges": [ "MANAGE_POLICIES" ],
                "actors": {
                  "users": ["urn:li:corpuser:datahub"],
                  "resourceOwners": False,
                  "allUsers": False,
                  "allGroups": False
                }
            }
        }
    }

    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["updatePolicy"]
    assert res_data["data"]["updatePolicy"] == "urn:li:dataHubPolicy:7"

@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion", "test_frontend_list_policies", "test_frontend_update_policy"])
def test_frontend_delete_policy(frontend_session):

    json = {
        "query": """mutation deletePolicy($urn: String!) {\n
            deletePolicy(urn: $urn) }""",
        "variables": {
            "urn": "urn:li:dataHubPolicy:7"
        }
    }

    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )
    response.raise_for_status()
    res_data = response.json()

    # Now verify the policy has been removed.
    json = {
        "query": """query listPolicies($input: ListPoliciesInput!) {\n
            listPolicies(input: $input) {\n
                start\n
                count\n
                total\n
                policies {\n
                    urn\n
                }\n
            }\n
        }""",
        "variables": {
            "input": {
              "start": "0",
              "count": "20",
            }
        }
    }
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["listPolicies"]
    assert len(res_data["data"]["listPolicies"]["policies"]) is 7 # Length of default policies - 1

@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion", "test_frontend_list_policies", "test_frontend_delete_policy"])
def test_frontend_create_policy(frontend_session):

    # Policy tests are not idempotent. If you rerun this test it will be wrong.
    json = {
        "query": """mutation createPolicy($input: PolicyUpdateInput!) {\n
            createPolicy(input: $input) }""",
        "variables": {
            "input": {
                "type": "METADATA",
                "name": "Test Metadata Policy",
                "description": "My Metadaata Policy",
                "state": "ACTIVE",
                "resources": {
                  "type": "dataset",
                  "allResources": True
                },
                "privileges": [ "EDIT_ENTITY_TAGS" ],
                "actors": {
                  "users": ["urn:li:corpuser:datahub"],
                  "resourceOwners": False,
                  "allUsers": False,
                  "allGroups": False
                }
            }
        }
    }

    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["createPolicy"]

    # Now verify the policy has been added.
    json = {
        "query": """query listPolicies($input: ListPoliciesInput!) {\n
            listPolicies(input: $input) {\n
                start\n
                count\n
                total\n
                policies {\n
                    urn\n
                }\n
            }\n
        }""",
        "variables": {
            "input": {
              "start": "0",
              "count": "20",
            }
        }
    }
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["listPolicies"]
    # TODO: Check to see that the policy we created in inside the array.
    assert len(res_data["data"]["listPolicies"]["policies"]) is 8 # Back up to 8

@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion"])
def test_frontend_app_config(frontend_session):

    json = {
        "query": """query appConfig {\n
            appConfig {\n
                analyticsConfig {\n
                  enabled\n
                }\n
                policiesConfig {\n
                  enabled\n
                  platformPrivileges {\n
                    type\n
                    displayName\n
                    description\n
                  }\n
                  resourcePrivileges {\n
                    resourceType\n
                    resourceTypeDisplayName\n
                    entityType\n
                    privileges {\n
                      type\n
                      displayName\n
                      description\n
                    }\n
                  }\n
                }\n
            }\n
        }"""
    }

    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["appConfig"]
    assert res_data["data"]["appConfig"]["analyticsConfig"]["enabled"] is True
    assert res_data["data"]["appConfig"]["policiesConfig"]["enabled"] is True

@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion"])
def test_frontend_me_query(frontend_session):

    json = {
        "query": """query me {\n
            me {\n
                corpUser {\n
                  urn\n
                  username\n
                  editableInfo {\n
                      pictureLink\n
                  }\n
                  info {\n
                      firstName\n
                      fullName\n
                      title\n
                      email\n
                  }\n
                }\n
                platformPrivileges {\n
                  viewAnalytics
                  managePolicies
                }\n
            }\n
        }"""
    }

    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["me"]["corpUser"]["urn"] == "urn:li:corpuser:datahub"
    assert res_data["data"]["me"]["platformPrivileges"]["viewAnalytics"] is True
    assert res_data["data"]["me"]["platformPrivileges"]["managePolicies"] is True



@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion"])
def test_add_tag(frontend_session):
    platform = "urn:li:dataPlatform:kafka"
    dataset_name = (
        "SampleKafkaDataset"
    )
    env = "PROD"
    dataset_urn = f"urn:li:dataset:({platform},{dataset_name},{env})"

    dataset_json = {
        "query": """query getDataset($urn: String!) {\n
            dataset(urn: $urn) {\n
                globalTags {\n
                    tags {\n
                        tag {\n
                            urn\n
                            name\n
                            description\n
                        }\n
                    }\n
                }\n
            }\n
        }""",
        "variables": {
            "urn": dataset_urn
        }
    }

    # Fetch tags
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=dataset_json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["dataset"]
    assert res_data["data"]["dataset"]["globalTags"] == None

    add_json = {
        "query": """mutation addTag($input: TagAssociationInput!) {\n
            addTag(input: $input)
        }""",
        "variables": {
            "input": {
              "tagUrn": "urn:li:tag:Legacy",
              "resourceUrn": dataset_urn,
            }
        }
    }

    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=add_json
    )
    response.raise_for_status()
    res_data = response.json()

    print(res_data)

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["addTag"] is True

    # Refetch the dataset
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=dataset_json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["dataset"]
    assert res_data["data"]["dataset"]["globalTags"] == {'tags': [{'tag': {'description': 'Indicates the dataset is no longer supported', 'name': 'Legacy', 'urn': 'urn:li:tag:Legacy'}}]}

    remove_json = {
        "query": """mutation removeTag($input: TagAssociationInput!) {\n
            removeTag(input: $input)
        }""",
        "variables": {
            "input": {
              "tagUrn": "urn:li:tag:Legacy",
              "resourceUrn": dataset_urn,
            }
        }
    }

    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=remove_json
    )
    response.raise_for_status()
    res_data = response.json()

    print(res_data)

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["removeTag"] is True

    # Refetch the dataset
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=dataset_json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["dataset"]
    assert res_data["data"]["dataset"]["globalTags"] == {'tags': [] }


@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion"])
def test_add_tag_to_chart(frontend_session):
    chart_urn = "urn:li:chart:(looker,baz2)"

    chart_json = {
        "query": """query getChart($urn: String!) {\n
            chart(urn: $urn) {\n
                globalTags {\n
                    tags {\n
                        tag {\n
                            urn\n
                            name\n
                            description\n
                        }\n
                    }\n
                }\n
            }\n
        }""",
        "variables": {
            "urn": chart_urn
        }
    }

    # Fetch tags
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=chart_json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["chart"]
    assert res_data["data"]["chart"]["globalTags"] == None

    add_json = {
        "query": """mutation addTag($input: TagAssociationInput!) {\n
            addTag(input: $input)
        }""",
        "variables": {
            "input": {
              "tagUrn": "urn:li:tag:Legacy",
              "resourceUrn": chart_urn,
            }
        }
    }

    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=add_json
    )
    response.raise_for_status()
    res_data = response.json()

    print(res_data)

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["addTag"] is True

    # Refetch the dataset
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=chart_json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["chart"]
    assert res_data["data"]["chart"]["globalTags"] == {'tags': [{'tag': {'description': 'Indicates the dataset is no longer supported', 'name': 'Legacy', 'urn': 'urn:li:tag:Legacy'}}]}

    remove_json = {
        "query": """mutation removeTag($input: TagAssociationInput!) {\n
            removeTag(input: $input)
        }""",
        "variables": {
            "input": {
              "tagUrn": "urn:li:tag:Legacy",
              "resourceUrn": chart_urn,
            }
        }
    }

    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=remove_json
    )
    response.raise_for_status()
    res_data = response.json()

    print(res_data)

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["removeTag"] is True

    # Refetch the dataset
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=chart_json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["chart"]
    assert res_data["data"]["chart"]["globalTags"] == {'tags': [] }

@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion"])
def test_add_term(frontend_session):
    platform = "urn:li:dataPlatform:kafka"
    dataset_name = (
        "SampleKafkaDataset"
    )
    env = "PROD"
    dataset_urn = f"urn:li:dataset:({platform},{dataset_name},{env})"

    dataset_json = {
        "query": """query getDataset($urn: String!) {\n
            dataset(urn: $urn) {\n
                glossaryTerms {\n
                    terms {\n
                        term {\n
                            urn\n
                            name\n
                        }\n
                    }\n
                }\n
            }\n
        }""",
        "variables": {
            "urn": dataset_urn
        }
    }


    # Fetch the terms
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=dataset_json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["dataset"]
    assert res_data["data"]["dataset"]["glossaryTerms"] == None

    add_json = {
        "query": """mutation addTerm($input: TermAssociationInput!) {\n
            addTerm(input: $input)
        }""",
        "variables": {
            "input": {
              "termUrn": "urn:li:glossaryTerm:SavingAccount",
              "resourceUrn": dataset_urn,
            }
        }
    }

    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=add_json
    )
    response.raise_for_status()
    res_data = response.json()

    print(res_data)

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["addTerm"] is True

    # Refetch the dataset
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=dataset_json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["dataset"]
    assert res_data["data"]["dataset"]["glossaryTerms"] == {'terms': [{'term': {'name': 'SavingAccount', 'urn': 'urn:li:glossaryTerm:SavingAccount'}}]}

    remove_json = {
        "query": """mutation removeTerm($input: TermAssociationInput!) {\n
            removeTerm(input: $input)
        }""",
        "variables": {
            "input": {
              "termUrn": "urn:li:glossaryTerm:SavingAccount",
              "resourceUrn": dataset_urn,
            }
        }
    }

    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=remove_json
    )
    response.raise_for_status()
    res_data = response.json()

    print(res_data)

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["removeTerm"] is True
    # Refetch the dataset
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=dataset_json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["dataset"]
    assert res_data["data"]["dataset"]["glossaryTerms"] == {'terms': []}


@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion"])
def test_update_schemafield(frontend_session):
    platform = "urn:li:dataPlatform:kafka"
    dataset_name = (
        "SampleKafkaDataset"
    )
    env = "PROD"
    dataset_urn = f"urn:li:dataset:({platform},{dataset_name},{env})"

    dataset_schema_json_terms = {
        "query": """query getDataset($urn: String!) {\n
            dataset(urn: $urn) {\n
                urn\n
                name\n
                description\n
                platform {\n
                    urn\n
                }\n
                editableSchemaMetadata {\n
                    editableSchemaFieldInfo {\n
                        glossaryTerms {\n
                            terms {\n
                                term {\n
                                    urn\n
                                    name\n
                                }\n
                            }\n
                        }\n
                    }\n
                }\n
            }\n
        }""",
        "variables": {
            "urn": dataset_urn
        }
    }

    dataset_schema_json_tags  = {
        "query": """query getDataset($urn: String!) {\n
            dataset(urn: $urn) {\n
                urn\n
                name\n
                description\n
                platform {\n
                    urn\n
                }\n
                editableSchemaMetadata {\n
                    editableSchemaFieldInfo {\n
                        globalTags {\n
                            tags {\n
                                tag {\n
                                    urn\n
                                    name\n
                                    description\n
                                }\n
                            }\n
                        }\n
                    }\n
                }\n
            }\n
        }""",
        "variables": {
            "urn": dataset_urn
        }
    }

    dataset_schema_json_description  = {
        "query": """query getDataset($urn: String!) {\n
            dataset(urn: $urn) {\n
                urn\n
                name\n
                description\n
                platform {\n
                    urn\n
                }\n
                editableSchemaMetadata {\n
                    editableSchemaFieldInfo {\n
                      description\n
                    }\n
                }\n
            }\n
        }""",
        "variables": {
            "urn": dataset_urn
        }
    }

    # dataset schema tags
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=dataset_schema_json_tags
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["dataset"]
    assert res_data["data"]["dataset"]["editableSchemaMetadata"] == None

    add_json = {
        "query": """mutation addTag($input: TagAssociationInput!) {\n
            addTag(input: $input)
        }""",
        "variables": {
            "input": {
              "tagUrn": "urn:li:tag:Legacy",
              "resourceUrn": dataset_urn,
              "subResource": "[version=2.0].[type=boolean].field_bar",
              "subResourceType": "DATASET_FIELD"
            }
        }
    }

    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=add_json
    )
    response.raise_for_status()
    res_data = response.json()

    print(res_data)

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["addTag"] is True

    # Refetch the dataset schema
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=dataset_schema_json_tags
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["dataset"]
    assert res_data["data"]["dataset"]["editableSchemaMetadata"] == {'editableSchemaFieldInfo': [{'globalTags': {'tags': [{'tag': {'description': 'Indicates the dataset is no longer supported', 'name': 'Legacy', 'urn': 'urn:li:tag:Legacy'}}]}}]}

    remove_json = {
        "query": """mutation removeTag($input: TagAssociationInput!) {\n
            removeTag(input: $input)
        }""",
        "variables": {
            "input": {
              "tagUrn": "urn:li:tag:Legacy",
              "resourceUrn": dataset_urn,
              "subResource": "[version=2.0].[type=boolean].field_bar",
              "subResourceType": "DATASET_FIELD"
            }
        }
    }

    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=remove_json
    )
    response.raise_for_status()
    res_data = response.json()

    print(res_data)

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["removeTag"] is True

    # Refetch the dataset
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=dataset_schema_json_tags
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["dataset"]
    assert res_data["data"]["dataset"]["editableSchemaMetadata"] == {'editableSchemaFieldInfo': [{'globalTags': {'tags': []}}]}

    add_json = {
        "query": """mutation addTerm($input: TermAssociationInput!) {\n
            addTerm(input: $input)
        }""",
        "variables": {
            "input": {
              "termUrn": "urn:li:glossaryTerm:SavingAccount",
              "resourceUrn": dataset_urn,
              "subResource": "[version=2.0].[type=boolean].field_bar",
              "subResourceType": "DATASET_FIELD"
            }
        }
    }

    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=add_json
    )
    response.raise_for_status()
    res_data = response.json()

    print(res_data)

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["addTerm"] is True

    # Refetch the dataset schema
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=dataset_schema_json_terms
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["dataset"]
    assert res_data["data"]["dataset"]["editableSchemaMetadata"] == {'editableSchemaFieldInfo': [{'glossaryTerms': {'terms': [{'term': {'name': 'SavingAccount', 'urn': 'urn:li:glossaryTerm:SavingAccount'}}]}}]}

    remove_json = {
        "query": """mutation removeTerm($input: TermAssociationInput!) {\n
            removeTerm(input: $input)
        }""",
        "variables": {
            "input": {
              "termUrn": "urn:li:glossaryTerm:SavingAccount",
              "resourceUrn": dataset_urn,
              "subResource": "[version=2.0].[type=boolean].field_bar",
              "subResourceType": "DATASET_FIELD"
            }
        }
    }

    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=remove_json
    )
    response.raise_for_status()
    res_data = response.json()

    print(res_data)

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["removeTerm"] is True

    # Refetch the dataset
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=dataset_schema_json_terms
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["dataset"]
    assert res_data["data"]["dataset"]["editableSchemaMetadata"] == {'editableSchemaFieldInfo': [{'glossaryTerms': {'terms': []}}]}

    # dataset schema tags
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=dataset_schema_json_tags
    )
    response.raise_for_status()
    res_data = response.json()

    update_description_json = {
        "query": """mutation updateDescription($input: DescriptionUpdateInput!) {\n
            updateDescription(input: $input)
        }""",
        "variables": {
            "input": {
              "description": "new description",
              "resourceUrn": dataset_urn,
              "subResource": "[version=2.0].[type=boolean].field_bar",
              "subResourceType": "DATASET_FIELD"
            }
        }
    }

    # fetch no description
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=dataset_schema_json_description
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["dataset"]
    assert res_data["data"]["dataset"]["editableSchemaMetadata"] == {'editableSchemaFieldInfo': [{ 'description': None }]}

    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=update_description_json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["updateDescription"] is True

    # Refetch the dataset
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=dataset_schema_json_description
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["dataset"]
    assert res_data["data"]["dataset"]["editableSchemaMetadata"] == {'editableSchemaFieldInfo': [{'description': 'new description'}]}

@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion"])
def test_list_users(frontend_session):

    json = {
        "query": """query listUsers($input: ListUsersInput!) {\n
            listUsers(input: $input) {\n
                start\n
                count\n
                total\n
                users {\n
                    urn\n
                    type\n
                    username\n
                    properties {\n
                      firstName
                    }\n
                }\n
            }\n
        }""",
        "variables": {
            "input": {
              "start": "0",
              "count": "2",
            }
        }
    }
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["listUsers"]
    assert res_data["data"]["listUsers"]["start"] is 0
    assert res_data["data"]["listUsers"]["count"] is 2
    assert len(res_data["data"]["listUsers"]["users"]) is 2 # Length of default user set.

@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion"])
def test_list_groups(frontend_session):

    json = {
        "query": """query listGroups($input: ListGroupsInput!) {\n
            listGroups(input: $input) {\n
                start\n
                count\n
                total\n
                groups {\n
                    urn\n
                    type\n
                    name\n
                    properties {\n
                      displayName
                    }\n
                }\n
            }\n
        }""",
        "variables": {
            "input": {
              "start": "0",
              "count": "2",
            }
        }
    }
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["listGroups"]
    assert res_data["data"]["listGroups"]["start"] is 0
    assert res_data["data"]["listGroups"]["count"] is 2
    assert len(res_data["data"]["listGroups"]["groups"]) is 2 # Length of default group set.

@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion", "test_list_groups"])
def test_add_remove_members_from_group(frontend_session):

    # Assert no group edges for user jdoe
    json = {
        "query": """query corpUser($urn: String!) {\n
            corpUser(urn: $urn) {\n
                urn\n
                relationships(input: { types: ["IsMemberOfGroup"], direction: OUTGOING, start: 0, count: 1 }) {\n
                    total\n
                }\n
            }\n
        }""",
        "variables": {
            "urn": "urn:li:corpuser:jdoe"
        }
    }
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["corpUser"]
    assert res_data["data"]["corpUser"]["relationships"]["total"] is 0

    # Add jdoe to group
    json = {
        "query": """mutation addGroupMembers($input: AddGroupMembersInput!) {\n
            addGroupMembers(input: $input) }""",
        "variables": {
            "input": {
                "groupUrn": "urn:li:corpGroup:bfoo",
                "userUrns": [ "urn:li:corpuser:jdoe" ],
            }
        }
    }

    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )
    response.raise_for_status()

    # Sleep for edge store to be updated. Not ideal!
    time.sleep(1)

    # Verify the member has been added
    json = {
        "query": """query corpUser($urn: String!) {\n
            corpUser(urn: $urn) {\n
                urn\n
                relationships(input: { types: ["IsMemberOfGroup"], direction: OUTGOING, start: 0, count: 1 }) {\n
                    total\n
                }\n
            }\n
        }""",
        "variables": {
            "urn": "urn:li:corpuser:jdoe"
        }
    }
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["corpUser"]
    assert res_data["data"]["corpUser"]["relationships"]["total"] is 1

    # Now remove jdoe from the group
    json = {
        "query": """mutation removeGroupMembers($input: RemoveGroupMembersInput!) {\n
            removeGroupMembers(input: $input) }""",
        "variables": {
            "input": {
                "groupUrn": "urn:li:corpGroup:bfoo",
                "userUrns": [ "urn:li:corpuser:jdoe" ],
            }
        }
    }

    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )
    response.raise_for_status()

    # Sleep for edge store to be updated. Not ideal!
    time.sleep(1)

    # Verify the member has been removed
    json = {
        "query": """query corpUser($urn: String!) {\n
            corpUser(urn: $urn) {\n
                urn\n
                relationships(input: { types: ["IsMemberOfGroup"], direction: OUTGOING, start: 0, count: 1 }) {\n
                    total\n
                }\n
            }\n
        }""",
        "variables": {
            "urn": "urn:li:corpuser:jdoe"
        }
    }
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["corpUser"]
    assert res_data["data"]["corpUser"]["relationships"]["total"] is 0

@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion", "test_list_groups", "test_add_remove_members_from_group"])
def test_remove_user(frontend_session):

    json = {
        "query": """mutation removeUser($urn: String!) {\n
            removeUser(urn: $urn) }""",
        "variables": {
            "urn": "urn:li:corpuser:jdoe"
        }
    }

    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )
    response.raise_for_status()

    json = {
        "query": """query corpUser($urn: String!) {\n
            corpUser(urn: $urn) {\n
                urn\n
                properties {\n
                    firstName\n
                }\n
            }\n
        }""",
        "variables": {
            "urn": "urn:li:corpuser:jdoe"
        }
    }
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["corpUser"]
    assert res_data["data"]["corpUser"]["properties"] is None

@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion", "test_list_groups", "test_add_remove_members_from_group"])
def test_remove_group(frontend_session):

    json = {
        "query": """mutation removeGroup($urn: String!) {\n
            removeGroup(urn: $urn) }""",
        "variables": {
          "urn": "urn:li:corpGroup:bfoo"
        }
    }

    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )
    response.raise_for_status()

    json = {
        "query": """query corpGroup($urn: String!) {\n
            corpGroup(urn: $urn) {\n
                urn\n
                properties {\n
                    displayName\n
                }\n
            }\n
        }""",
        "variables": {
            "urn": "urn:li:corpGroup:bfoo"
        }
    }
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["corpGroup"]
    assert res_data["data"]["corpGroup"]["properties"] is None

@pytest.mark.dependency(depends=["test_healthchecks", "test_run_ingestion", "test_list_groups", "test_remove_group"])
def test_create_group(frontend_session):

    json = {
        "query": """mutation createGroup($input: CreateGroupInput!) {\n
            createGroup(input: $input) }""",
        "variables": {
            "input": {
                "name": "Test Group",
                "description": "My test group"
            }
        }
    }

    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )
    response.raise_for_status()

    json = {
        "query": """query corpGroup($urn: String!) {\n
            corpGroup(urn: $urn) {\n
                urn\n
                properties {\n
                    displayName\n
                }\n
            }\n
        }""",
        "variables": {
          "urn": "urn:li:corpGroup:Test Group"
        }
    }
    response = frontend_session.post(
        f"{FRONTEND_ENDPOINT}/api/v2/graphql", json=json
    )
    response.raise_for_status()
    res_data = response.json()

    assert res_data
    assert res_data["data"]
    assert res_data["data"]["corpGroup"]
    assert res_data["data"]["corpGroup"]["properties"]["displayName"] == "Test Group"