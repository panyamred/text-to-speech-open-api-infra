import subprocess

from scripts.utilities import cmd_runner, ordered_load
import yaml


class EnvoyConfig:

    def __init__(self, base_name, helm_chart_path):
        self.name = "envoy"
        self.helm_chart_path = helm_chart_path
        self.release_name = "{}-{}".format(base_name, self.name)

    def is_deployed(self, namespace):
        result = subprocess.getoutput('helm status {} -n {} --output yaml'.format(self.release_name, namespace))
        if "release: not found" in result.lower():
            return False
        else:
            return True

    def deploy(self, namespace):
        isdeployed = self.is_deployed(namespace)
        if not isdeployed:
            process = "install"
        else:
            process = "upgrade"

        command = "helm {0} --timeout 180s {1} {2} --namespace {3}".format(process, self.release_name,
                                                                           self.helm_chart_path, namespace)
        cmd_runner(command, "Envoy")


def get_cluster(clusters, language_code):
    cluster_name = "{}_cluster".format(language_code)
    for cluster in clusters:
        if cluster["name"] == cluster_name:
            return cluster
    return None


def create_cluster(language_code, release_name):
    cluster = '''
        name: api_cluster
        type: LOGICAL_DNS
        lb_policy: ROUND_ROBIN
        connect_timeout: 30s
        dns_lookup_family: V4_ONLY
        load_assignment:
          cluster_name: api_cluster
          endpoints:
          - lb_endpoints:
            - endpoint:
                address:
                  socket_address:
                    address: localhost
                    port_value: 50052
    '''
    cluster = ordered_load(cluster, yaml.SafeLoader)
    cluster_name = "{}_cluster".format(language_code)
    cluster["name"] = cluster_name
    cluster["load_assignment"]["cluster_name"] = cluster_name
    cluster["load_assignment"]["endpoints"][0]["lb_endpoints"][0]["endpoint"]["address"]["socket_address"][
        "address"] = release_name
    return cluster


def verify_and_update_release_name(cluster, release_name):
    address = cluster["load_assignment"]["endpoints"][0]["lb_endpoints"][0]["endpoint"]["address"]["socket_address"][
        "address"]
    if address != release_name:
        cluster["load_assignment"]["endpoints"][0]["lb_endpoints"][0]["endpoint"]["address"]["socket_address"][
            "address"] = release_name


def get_rest_match_filter(method_name, routes, language_code):
    path_to_match = "/v1/{}/{}".format(method_name, language_code)
    for route in routes:
        if "prefix" in route["match"] and route["match"]["prefix"] == path_to_match:
            return route
    return None


def create_rest_match_filter(method_name, language_code, cluster_name):
    route_match = '''
        match:
          prefix: "/v1/{}/hi"
        route:
          cluster: hi_cluster
          timeout: 60s
    '''.format(method_name)
    route_match = ordered_load(route_match, yaml.SafeLoader)
    route_match["match"]["prefix"] = "/v1/{}/{}".format(method_name, language_code)
    route_match["route"]["cluster"] = cluster_name
    return route_match


def update_envoy_config(config, language_config):
    methods_config = [
        {"name": "tts", "enable_rest_match": True}
    ]

    listeners = config["static_resources"]["listeners"]
    clusters = config["static_resources"]["clusters"]
    routes = listeners[0]["filter_chains"][0]["filters"][0]["typed_config"]["route_config"]["virtual_hosts"][0][
        "routes"]

    # updating cluster information
    cluster = get_cluster(clusters, language_config.get_language_code())
    if cluster is None:
        lang_cluster = create_cluster(language_config.get_language_code(), language_config.release_name)
        clusters.append(lang_cluster)
        cluster = lang_cluster
    else:
        verify_and_update_release_name(cluster, language_config.release_name)
    # updating match filter
    language_codes = language_config.get_language_code_as_list()
    initial_routes_length = len(routes)
    for language_code in language_codes:
        for method_config in methods_config:
            method_name = method_config["name"]

            if "enable_rest_match" in method_config and (method_config["enable_rest_match"] == True):
                rest_match_route = get_rest_match_filter(method_name, routes, language_code)
                if rest_match_route is None:
                    rest_match_route = create_rest_match_filter(method_name, language_code, cluster["name"])
                    routes.insert(len(routes) - initial_routes_length, rest_match_route)

    return config