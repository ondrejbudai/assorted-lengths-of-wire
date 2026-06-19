# EC2 Spot Analyzer

Analyzes EC2 spot instance interruption frequency using data from the
[AWS Spot Advisor](https://aws.amazon.com/ec2/spot/instance-advisor/).
Architecture is inferred from instance type names. Optionally fetches
live spot and on-demand prices via the AWS APIs.

## Usage

### Run directly from GitHub

```sh
uv run https://raw.githubusercontent.com/ondrejbudai/assorted-lengths-of-wire/main/ec2-spot-analyzer/ec2_spot_analyzer.py --help
```

### Run from a local clone

```sh
uv run ec2_spot_analyzer.py --region us-east-1 --arch aarch64 --vcpu 4 --memory 16
```

## Arguments

| Argument   | Description                                                | Default      |
|------------|------------------------------------------------------------|--------------|
| `--region` | AWS region                                                 | `us-east-1`  |
| `--vcpu`   | vCPU filter: exact value (`4`) or range (`4-16`)           | (no filter)  |
| `--memory` | Memory filter in GB: exact value (`16`) or range (`16-64`) | (no filter)  |
| `--arch`   | CPU architecture: `x86_64` or `aarch64`                    | (no filter)  |
| `--prices` | Fetch spot and on-demand prices (requires AWS credentials)  | off          |

## Examples

Without `--prices` (no AWS credentials needed):

```
$ uv run ec2_spot_analyzer.py --region us-east-1 --arch aarch64 --vcpu 4 --memory 16
Instance Type  vCPU  Memory (GB)  Arch     Frequency
-------------  ----  -----------  -------  ---------
m6g.xlarge        4         16.0  aarch64  >20%
m6gd.xlarge       4         16.0  aarch64  >20%
m8g.xlarge        4         16.0  aarch64  >20%
...
m8gd.xlarge       4         16.0  aarch64  <5%
```

With `--prices` (requires AWS credentials with `ec2:DescribeSpotPriceHistory`
and `pricing:GetProducts` permissions):

```
$ uv run ec2_spot_analyzer.py --region us-east-1 --arch aarch64 --vcpu 4 --memory 16 --prices
Instance Type  vCPU  Memory (GB)  Arch     Frequency  Spot ¢/hr  On-Demand ¢/hr
-------------  ----  -----------  -------  ---------  ---------  --------------
m6g.xlarge        4         16.0  aarch64  >20%            6.37           15.40
m6gd.xlarge       4         16.0  aarch64  >20%           11.63           18.08
...
m8gd.xlarge       4         16.0  aarch64  <5%             8.32           23.06
```

Output is sorted by interruption frequency (highest first).
