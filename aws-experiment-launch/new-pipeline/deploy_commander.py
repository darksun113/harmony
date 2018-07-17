import boto3
import argparse
import sys
import json
import time
import datetime
from threading import Thread
from Queue import Queue
import base64
import subprocess


class InstanceResource:
    ON_DEMAND = 1
    SPOT_INSTANCE = 2
    SPOT_FLEET = 3


REGION_NAME = 'region_name'
REGION_KEY = 'region_key'
REGION_SECURITY_GROUP = 'region_security_group'
REGION_SECURITY_GROUP_ID = 'region_security_group_id'
REGION_HUMAN_NAME = 'region_human_name'
INSTANCE_TYPE = 't2.micro'
REGION_AMI = 'region_ami'
with open("userdata-commander.sh", "r") as userdata_file:
    USER_DATA = userdata_file.read()

# UserData must be base64 encoded for spot instances.
USER_DATA_BASE64 = base64.b64encode(USER_DATA)

IAM_INSTANCE_PROFILE = 'BenchMarkCodeDeployInstanceProfile'
REPO = "simple-rules/harmony-benchmark"
APPLICATION_NAME = 'benchmark-experiments'
time_stamp = time.time()
CURRENT_SESSION = datetime.datetime.fromtimestamp(
    time_stamp).strftime('%H-%M-%S-%Y-%m-%d')
PLACEMENT_GROUP = "PLACEMENT-" + CURRENT_SESSION
NODE_NAME_SUFFIX = "NODE-" + CURRENT_SESSION
REPO = "simple-rules/harmony-benchmark"

def create_launch_specification(region_number, instanceType):
    NODE_NAME = region_number + "-" + NODE_NAME_SUFFIX
    return {
        # Region irrelevant fields
        'IamInstanceProfile': {
            'Name': IAM_INSTANCE_PROFILE
        },
        'InstanceType': instanceType,
        'UserData': USER_DATA_BASE64,
        # Region relevant fields
        'SecurityGroups': [
            {
                # In certain scenarios, we have to use group id instead of group name
                # https://github.com/boto/boto/issues/350#issuecomment-27359492
                'GroupId': config[region_number][REGION_SECURITY_GROUP_ID]
            }
        ],
        'ImageId': config[region_number][REGION_AMI],
        'KeyName': config[region_number][REGION_KEY],
        'UserData': USER_DATA_BASE64,
        'TagSpecifications': [
            {
                'ResourceType': 'instance',
                'Tags': [
                    {
                        'Key': 'Name',
                        'Value': NODE_NAME
                    }
                ]
            }
        ],
        # 'WeightedCapacity': 123.0,
        # 'Placement': {
        #     # 'AvailabilityZone': get_one_availability_zone(ec2_client)
        # }
    }


def create_launch_specification_list(region_number, instance_type_list):
    return list(map(lambda type: create_launch_specification(region_number, type), instance_type_list))


"""
TODO:

Build (argparse,functions) support for 
1. run only create instance (multiple times)
2. run only codedeploy (multiple times)
3. run create instance followed by codedeploy

"""

### CREATE INSTANCES ###


def run_one_region_instances(config, region_number, number_of_instances, instance_resource=InstanceResource.ON_DEMAND):
    #todo: explore the use ec2 resource and not client. e.g. create_instances --  Might make for better code.
    """
    e.g. ec2.create_instances
    """
    region_name = config[region_number][REGION_NAME]
    session = boto3.Session(region_name=region_name)
    ec2_client = session.client('ec2')
    if instance_resource == InstanceResource.ON_DEMAND:
        NODE_NAME = create_instances(
            config, ec2_client, region_number, int(number_of_instances))
        # REPLACE ALL print with logger
        print("Created %s in region %s" % (NODE_NAME, region_number))
    elif instance_resource == InstanceResource.SPOT_INSTANCE:
        response = request_spot_instances(
            config, ec2_client, region_number, int(number_of_instances))
    else:
        instance_type_list = ['t2.micro', 't2.small', 'm3.medium']
        response = request_spot_fleet(
            config, ec2_client, region_number, int(number_of_instances), instance_type_list)
        return
    return session


def create_instances(config, ec2_client, region_number, number_of_instances):
    NODE_NAME = region_number + "-" + NODE_NAME_SUFFIX
    response = ec2_client.run_instances(
        MinCount=number_of_instances,
        MaxCount=number_of_instances,
        ImageId=config[region_number][REGION_AMI],
        Placement={
            'AvailabilityZone': get_one_availability_zone(ec2_client),
        },
        SecurityGroups=[config[region_number][REGION_SECURITY_GROUP]],
        IamInstanceProfile={
            'Name': IAM_INSTANCE_PROFILE
        },
        KeyName=config[region_number][REGION_KEY],
        UserData=USER_DATA,
        InstanceType=INSTANCE_TYPE,
        TagSpecifications=[
            {
                'ResourceType': 'instance',
                'Tags': [
                    {
                        'Key': 'Name',
                        'Value': NODE_NAME
                    },
                ]
            },
        ],
    )
    return NODE_NAME


def request_spot_instances(config, ec2_client, region_number, number_of_instances):
    NODE_NAME = region_number + "-" + NODE_NAME_SUFFIX
    response = ec2_client.request_spot_instances(
        # DryRun=True,
        BlockDurationMinutes=60,
        InstanceCount=number_of_instances,
        LaunchSpecification={
            'SecurityGroups': [config[region_number][REGION_SECURITY_GROUP]],
            'IamInstanceProfile': {
                'Name': IAM_INSTANCE_PROFILE
            },
            'UserData': USER_DATA_BASE64,
            'ImageId': config[region_number][REGION_AMI],
            'InstanceType': INSTANCE_TYPE,
            'KeyName': config[region_number][REGION_KEY],
            'Placement': {
                'AvailabilityZone': get_one_availability_zone(ec2_client)
            }
        }
    )
    return response


def request_spot_fleet(config, ec2_client, region_number, number_of_instances, instance_type_list):
    NODE_NAME = region_number + "-" + NODE_NAME_SUFFIX
    # https://boto3.readthedocs.io/en/latest/reference/services/ec2.html#EC2.Client.request_spot_fleet
    response = ec2_client.request_spot_fleet(
        # DryRun=True,
        SpotFleetRequestConfig={
            # https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-fleet.html#spot-fleet-allocation-strategy
            'AllocationStrategy': 'diversified',
            'IamFleetRole': 'arn:aws:iam::656503231766:role/RichardFleetRole',
            'LaunchSpecifications': create_launch_specification_list(region_number, instance_type_list),
            # 'SpotPrice': 'string', # The maximum price per unit hour that you are willing to pay for a Spot Instance. The default is the On-Demand price.
            'TargetCapacity': number_of_instances,
            'OnDemandTargetCapacity': 0,
            'Type': 'maintain'
        }
    )
    return response


def get_availability_zones(ec2_client):
    response = ec2_client.describe_availability_zones()
    all_zones = []
    if response.get('AvailabilityZones', None):
       region_info = response.get('AvailabilityZones')
       for info in region_info:
           if info['State'] == 'available':
               all_zones.append(info['ZoneName'])
    return all_zones


def get_one_availability_zone(ec2_client):
    all_zones = get_availability_zones(ec2_client)
    if len(all_zones) > 0:
        return all_zones[0]
    else:
        print("No availability zone for this region")
        sys.exit()

#### CODEDEPLOY ###


def run_one_region_codedeploy(region_number, commitId):
    #todo: explore the use ec2 resource and not client. e.g. create_instances --  Might make for better code.
    """
    for getting instance ids:---
    ec2 = boto3.resource('ec2', region_name=region_name])
    result = ec2.instances.filter(Filters=[{'Name': 'instance-state-name', 'Values': ['running']}])
    for instance in result:
        instances.append(instance.id)
    
    for getting public ips : --
        ec2 = boto3.resource('ec2')
        instance
    """
    region_name = config[region_number][REGION_NAME]
    NODE_NAME = region_number + "-" + NODE_NAME_SUFFIX
    session = boto3.Session(region_name=region_name)
    ec2_client = session.client('ec2')
    filters = [{'Name': 'tag:Name', 'Values': [NODE_NAME]}]
    instance_ids = get_instance_ids(
        ec2_client.describe_instances(Filters=filters))

    print("Number of instances: %d" % len(instance_ids))

    print("Waiting for all %d instances in region %s to start running" %
          (len(instance_ids), region_number))
    waiter = ec2_client.get_waiter('instance_running')
    waiter.wait(InstanceIds=instance_ids)

    print("Waiting for all %d instances in region %s to be INSTANCE STATUS OK" % (
        len(instance_ids), region_number))
    waiter = ec2_client.get_waiter('instance_status_ok')
    waiter.wait(InstanceIds=instance_ids)

    print("Waiting for all %d instances in region %s to be SYSTEM STATUS OK" %
          (len(instance_ids), region_number))
    waiter = ec2_client.get_waiter('system_status_ok')
    waiter.wait(InstanceIds=instance_ids)

    codedeploy = session.client('codedeploy')
    application_name = APPLICATION_NAME
    deployment_group = APPLICATION_NAME + "-" + \
        commitId[:6] + "-" + CURRENT_SESSION
    repo = REPO

    print("Setting up to deploy commitId %s on region %s" %
          (commitId, region_number))
    response = get_application(codedeploy, application_name)
    deployment_group = get_deployment_group(
        codedeploy, region_number, application_name, deployment_group)
    depId = deploy(codedeploy, application_name,
                   deployment_group, repo, commitId)
    return region_number, depId


def get_deployment_group(codedeploy, region_number, application_name, deployment_group):
    NODE_NAME = region_number + "-" + NODE_NAME_SUFFIX
    response = codedeploy.create_deployment_group(
        applicationName=application_name,
        deploymentGroupName=deployment_group,
        deploymentConfigName='CodeDeployDefault.AllAtOnce',
        serviceRoleArn='arn:aws:iam::656503231766:role/BenchMarkCodeDeployServiceRole',
        deploymentStyle={
            'deploymentType': 'IN_PLACE',
            'deploymentOption': 'WITHOUT_TRAFFIC_CONTROL'
        },
        ec2TagFilters=[
            {
                'Key': 'Name',
                'Value': NODE_NAME,
                'Type': 'KEY_AND_VALUE'
            }
        ]
    )
    return deployment_group


def get_application(codedeploy, application_name):
    response = codedeploy.list_applications()
    if application_name in response['applications']:
        return response
    else:
        response = codedeploy.create_application(
            applicationName=application_name,
            computePlatform='Server'
        )
    return response


def deploy(codedeploy, application_name, deployment_group, repo, commitId):
    """Deploy new code at specified revision to instance.

    arguments:
    - repo: GitHub repository path from which to get the code
    - commitId: commit ID to be deployed
    - wait: wait until the CodeDeploy finishes
    """
    print("Launching CodeDeploy with commit " + commitId)
    res = codedeploy.create_deployment(
        applicationName=application_name,
        deploymentGroupName=deployment_group,
        deploymentConfigName='CodeDeployDefault.AllAtOnce',
        description='benchmark experiments',
        revision={
            'revisionType': 'GitHub',
            'gitHubLocation': {
                    'repository': repo,
                    'commitId': commitId,
            }
        }
    )
    depId = res["deploymentId"]
    print("Deployment ID: " + depId)
    # The deployment is launched at this point, so exit unless asked to wait
    # until it finishes
    info = {'status': 'Created'}
    start = time.time()
    while info['status'] not in ('Succeeded', 'Failed', 'Stopped',) and (time.time() - start < 600.0):
        info = codedeploy.get_deployment(deploymentId=depId)['deploymentInfo']
        print(info['status'])
        time.sleep(15)
    if info['status'] == 'Succeeded':
        print("\nDeploy Succeeded")
        return depId
    else:
        print("\nDeploy Failed")
        print(info)
        return depId


def run_one_region_codedeploy_wrapper(region_number, commitId, queue):
    region_number, depId = run_one_region_codedeploy(region_number, commitId)
    queue.put((region_number, depId))


def launch_code_deploy(region_list, commitId):
    queue = Queue()
    jobs = []
    for i in range(len(region_list)):
        region_number = region_list[i]
        my_thread = Thread(target=run_one_region_codedeploy_wrapper, args=(
            region_number, commitId, queue))
        my_thread.start()
        jobs.append(my_thread)
    for my_thread in jobs:
        my_thread.join()
    results = [queue.get() for job in jobs]
    return results

##### UTILS ####


def get_instance_ids(describe_instances_response):
    instance_ids = []
    for reservation in describe_instances_response["Reservations"]:
        for instance in reservation["Instances"]:
            instance_ids.append(instance["InstanceId"])
    return instance_ids


def read_configuration_file(filename):
    config = {}
    with open(filename, 'r') as f:
        for myline in f:
            mylist = myline.strip().split(',')
            region_num = mylist[0]
            config[region_num] = {}
            config[region_num][REGION_NAME] = mylist[1]
            config[region_num][REGION_KEY] = mylist[2]
            config[region_num][REGION_SECURITY_GROUP] = mylist[3]
            config[region_num][REGION_HUMAN_NAME] = mylist[4]
            config[region_num][REGION_AMI] = mylist[5]
            config[region_num][REGION_SECURITY_GROUP_ID] = mylist[6]
    return config

##### UTILS ####

def get_head_commit_id():
    git_head_hash = None
    try:
        process = subprocess.Popen(['git', 'rev-parse', 'HEAD'], shell=False, stdout=subprocess.PIPE)
        git_head_hash = process.communicate()[0].strip()
    finally:
        return git_head_hash

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='This script helps you start instances across multiple regions')
    parser.add_argument('--region_number', type=str, dest='region_number',
                        default='3', help="Supply a csv list of all regions")
    parser.add_argument('--instances', type=str, dest='number_of_instances',
                        default='1', help='number of instances')
    parser.add_argument('--configuration', type=str,
                        dest='config', default='configuration.txt')
    parser.add_argument('--commitId', type=str, dest='commitId',default='f092d25d7a814622079fe92e9b36e10e46bc0d97')
    args = parser.parse_args()
    config = read_configuration_file(args.config)
    commitId = get_head_commit_id() or args.commitId
    run_one_region_instances(config, args.region_number, args.number_of_instances)
    results = run_one_region_codedeploy(args.region_number, commitId)
    print(results)