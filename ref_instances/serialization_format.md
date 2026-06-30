# Serialization format

### For lists of changes
```
<number of versions> <number of changes>
<list of changes in prescribed format, each change on new line>
```

Format of changes is following (yes, asterisk **is** a delimiter):
- `ADD_NEW_VERSION`: `0*<N>*<P>`,
  - `<N>`: order number of the new version
  - `<P>`: parent or empty
- `RESOURCE_WORKING_HOURS`: `1*<R>*<D>*<S>*<E>`,
  - `<R>`: id of the resource, indexed from 0
  - `<D>`: relative days, indexed from 0 (start of scheduling period)
  - `<S>`: new starting hour or empty (= unchanged)
  - `<E>`: new ending hour or empty (= unchanged)
- `ADD_IRREGULAR_WORKING_DAY`: `2*<R>*<D>`
  - `<R>`: id of the resource, indexed from 0
  - `<D>`: relative days, indexed from 0 (start of scheduling period)
- `REMOVE_WORKING_DAY`: `3*<R>*<D>`
  - `<R>`: id of the resource, indexed from 0
  - `<D>`: relative days, indexed from 0 (start of scheduling period)
- `ADD_RELEASE_DATE`: `4*<O>*<H>`
  - `<O>`: id of the order, indexed from 0
  - `<H>`: relative hours, indexed from 0 (start of scheduling period) 
- `REMOVE_RELEASE_DATE`: `5*<O>`,
  - `<O>`: id of the order, indexed from 0
- `ADD_DEADLINE`: `6*<O>*<H>`
  - `<O>`: id of the order, indexed from 0
  - `<H>`: relative hours, indexed from 0 (start of scheduling period)
- `REMOVE_DEADLINE`: `7*<O>`
  - `<O>`: id of the order, indexed from 0
- `CHANGE_WEIGHT`: `8*<O>*<W>`
  - `<O>`: id of the order, indexed from 0
  - `<W>`: numerical value of the new weight

### For schedules 
```
<string with name of the version>
<number of jobs>
<list of jobs and start times in prescribed format>
```

Format of jobs and start time is following (for each job):
```
<id of job, indexed from 0> <number of parts>
<<number of part, indexed from 0> <start of the part in relative hours>, on new line FOR EACH PART>
```

### For problem instances (partially from PSPlib)
Variables that are not particularly interesting are not explained, only their data type is given

```
************************************************************************
file with basedata            : <string>
initial value random generator: <int>
************************************************************************
projects                      :  <int>
jobs (incl. supersource/sink ):  <number of jobs>
horizon                       :  <length of the schedule if the jobs were processed sequentially>
RESOURCES
  - renewable                 :  <int>   R
  - nonrenewable              :  <int>   N
  - doubly constrained        :  <int>   D
************************************************************************
PROJECT INFORMATION:
pronr.  #jobs rel.date duedate tardcost  MPM-Time
<<int>  <int>  <int>    <int>    <int>    <int> on separate line FOR EACH PROJECT> 
************************************************************************
PRECEDENCE RELATIONS:
jobnr.    #modes  #successors   successors
<list of jobs in PRECEDENCE RELATIONS format>
************************************************************************
REQUESTS/DURATIONS:
jobnr. mode duration  <R X FOR EACH RESOURCE>
<list of jobs in REQUESTS/DURATIONS format>
************************************************************************
RESOURCEAVAILABILITIES:
<R X FOR EACH RESOURCE>
<availability delimited by space FOR EACH RESOURCE>
************************************************************************
DUE DATES:
<list of jobs in DUE DATES format>
************************************************************************
FINISHED_TASKS: 
<list of finished tasks, indexed from 0, delimited by space> 
************************************************************************
COMPONENTS:
<list of activities, each from different component, indexed from 0, delimited by space> 
************************************************************************
COMPONENT_WEIGHTS: 
<list of weights for components, delimited by space> 
************************************************************************
RESOURCE SHIFT MODES: 
<list of resources in RESOURCE SHIFT MODES format>
```

#### `PRECEDENCE RELATIONS` format (from PSPlib)
Format of precedence relations for one job:
```
<job id, indexed from 1> <int> <number of successors> <list of successors, indexed from 1, delimited by space>\n
```

#### `REQUESTS/DURATIONS` format (from PSPlib)
Format of requests/duration for one job:
```
<job id, indexed from 1> <int> <duration> <list of requests for all resources, delimited by space>\n
```

#### `DUE DATES` format
Format of due dates for one job:
```
<job id, indexed from 1> <due date in relative hours, indexed from 0 (start of scheduling period)>\n
```

#### `RESOURCE SHIFT MODES` format
Format of shift modes for one resource:
``` 
<resource id, indexed from 1> <1 or 2>\n
```