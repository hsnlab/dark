import json
import random


def load_nodes(file_name):
    with open(file_name, 'r') as infile:
        nodes=json.load(infile)
    return nodes


def gen_delay(nodes):
    res=[]
    num_nodes = len(nodes)
    for i in range(0, num_nodes-1):
        for j in range(i+1, num_nodes):
            res.append(
                {
                    "src": nodes[i]["zone"],
                    "dst": nodes[j]["zone"],
                    "bw": 10000000,
                    "delay": random.randint(40, 200)
                }
            )
    return res


def dump_result(result, fname='delay_mtx.json'):
    with open(fname, 'wb') as outfile:
        outfile.write(json.dumps(result, indent=4, ensure_ascii=False).encode('utf8'))


if __name__ == '__main__':
    nodes = load_nodes("osnodes.json")
    res = gen_delay(nodes)
    dump_result(res)
