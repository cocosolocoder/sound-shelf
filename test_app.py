#!/usr/bin/env python3
"""曲目收录/编辑接口与收录、编辑表单的回归测试。

通过子进程真实启动 SoundShelf 服务，用 HTTP 请求固定以下既有规则：

收录（POST /api/tracks 与首页手动收录表单的同一次保存）：
- 已有曲目使用某个来源时，再提交去掉首尾空白后相同的来源，即使名称、
  说明等资料不同，未勾选另存或明确选择不另存都返回 409；existing 列出
  该来源全部已有记录的标识与名称，按标识升序，不混入其他来源的曲目；
  这次拒绝不新增记录，也不改变任一已有记录的资料。
- save_as_new_version 为布尔值 true（首页勾选“另存为新版本”）才新增
  独立标识的新记录，保存本次提交的资料，原版本不被覆盖或合并，之后
  列表仍按标识顺序同时展示；同名但来源不同、来源仅有内部文字差异时
  普通收录直接成功，只有首尾空白被忽略。
- 只有标识与名称、来源缺失的旧记录不参加重复判断，不会因名称相同
  拦住新收录；save_as_new_version 只接受布尔值，字符串或数字返回 400
  并指出该字段，既不能当作同意另存，也不会写入任何新曲目。
- 必填资料校验（名称 title 与来源 source）：两项都必须是字符串，去掉
  首尾空白后不能为空。JSON 收录接口分别省略其中一项、提交 null、空串、
  只有空白的字符串，或把其中一项写成数字、布尔值、数组、对象时返回
  400，field 指向对应字段，错误文字说明名称或来源不合法；每次只让一个
  必填字段出错，另一项与全部选填资料即使都合法，也不能产生一条不完整
  的曲目，记录数量不增加。用例来源都使用尚未收录的文字，失败属于必填
  资料错误而不是来源重复冲突。对照：中文名称与含中文路径的来源可以
  收录，只有首尾空白被去掉，内部文字与标点原样保留；成功返回 201，
  响应记录与随后列表读到的记录一致；省略选填资料仍按时长未知、封面和
  说明为空、标签为空数组保存。
- 收录接口的时长（POST /api/tracks 的 duration）：名称和来源合法、来源
  尚未收录时，有限的非负整数与小数都能作为秒数保存，成功返回 201 与完整
  曲目，0 是已知时长（读回为数字 0，不能当成未知）；省略时长或明确提交
  null 才表示未知，成功记录中的时长为 null。随后读取曲目列表，在同一标识
  下读到同一秒数或未知状态，名称、来源与本次提交的其他合法资料一致；列表
  仍按标识升序，新增曲目不改变已有曲目的资料。时长为负数或非有限数值，或
  以字符串、布尔值、数组、对象提交时返回 400，field 指向 duration，文字
  说明时长有误；数字字符串即使看起来像合法秒数也不自动转换，false 不能
  变成 0（网页允许在输入框里填写数字文字，并不改变 JSON 接口对数字类型的
  要求）；其他资料都合法也不能保存部分内容：空曲库仍为空，已有曲库的记录
  数量、顺序与各条完整资料保持提交前状态，不留下只有名称或来源的残缺记录。
  同一来源明确另存新版本时遵守相同时长规则：合法时长随本次资料保存到新
  标识下，原版本的时长与其他资料保持原样；时长不合法时即使已明确同意另存，
  也报告时长错误，不新增版本、不覆盖旧曲目。
- 首页手动收录表单的名称或来源留空、只填空白时返回 400：页面显示
  失败提示，并在对应字段附近指出错误；回填保留本次填写的名称、来源、
  时长、封面、说明、标签及另存选择，不能用已有记录的资料替换；说明里
  的中文、换行和看起来像网页标签的内容仍按普通文字显示。用户只修正
  出错的必填项、保留错误页中的其他填写再保存，应新增一条采用本次完整
  资料的曲目，失败前填写的选填内容不能丢掉。错误提交前已有的曲目保留
  完整资料和列表顺序，记录数量不增加；空曲库中的失败提交也仍显示没有
  记录。
- 首页手动收录表单的时长填写方式决定保存结果：非负整数与有限的非负
  小数文字（首尾空白忽略）保存成功后 303 回首页，提示收录成功，列表
  中新增一条采用本次完整资料的曲目；时长按填写的秒数保存和展示
  （“243.5 秒”，不换算分钟，不把小数截成整数），随后曲目列表接口
  读到的时长与网页一致。填写“0”显示“0 秒”且仍是数字零；时长框留空
  或只填空白则保存为未知，列表显示“未知”，接口为 null。负数、普通
  文字、NaN、Infinity 或“1e999”等超出有限数值范围的文字返回 400，
  页面提示保存失败并在时长字段附近说明时长有误；时长框保留本次填写的
  原文，名称、来源、封面地址、说明、标签与另存为新版本的选择也全部
  回填，说明中的中文、换行与形似网页标签的文字仍按普通文字转义显示。
  时长错误时即使其余资料都合法也不新增任何曲目或保存部分资料：空曲库
  仍显示没有记录，已有曲目的完整资料、数量与列表顺序保持原样。用户在
  错误页只修正时长、保留其余填写后再次保存，只新增一条采用回填资料与
  修正后时长的曲目，失败提交不留下额外记录；来源重复与另存为新版本的
  既有规则在时长出错与修正流程中同样有效。

编辑（PATCH /api/tracks/{id} 与 /tracks/{id}/edit 表单）：
- 同一来源允许另存多个独立版本；编辑其中一条时，它自己不构成冲突，
  来源未改变（含仅首尾空白不同）时不拒绝其他资料的保存。
- 把来源改成其他曲目已使用的文字时返回 409，existing 按 id 升序列出
  实际占用该来源的记录；冲突后任何记录都不被改动，可换来源直接重试。
- 只有标识与名称、来源缺失的旧记录：省略来源可正常编辑且不参与判重；
  补填已被占用的来源同样适用拒绝保存规则。
- 曲库在服务启动前就已存在的旧记录（旧表只有标识与名称两列，来源、时长、
  封面地址、说明与标签均尚未保存）：首次打开时列表接口与首页直接提供原有
  记录，标识、名称与记录数量保持不变，列表仍按标识升序；旧标识可不从 1
  开始、中间有空缺，不重新编号、不补出不存在的曲目，名称相同的两条记录
  各自保留，中文名称中的内部空格、连续空行、引号与尖括号不被裁剪、合并或
  改写，首页按已有名称展示规则保留分行，并把形似网页标签的文字显示为普通
  文字。接口中来源、时长为 null，封面地址与说明为空字符串、标签为空数组；
  首页把旧记录尚未填写的来源、时长、封面与说明显示为未填写、标签显示为无；
  未知时长不被当成零秒，缺失来源也不凭名称或标识自动生成。进入其中一条旧
  曲目的编辑页看到原名称与对应的空资料，可保留来源空白、只补充合法时长与
  说明后保存并继续使用原标识，列表接口与重新打开的编辑页都能读到已保存
  内容，另一条旧记录不受影响。同一次编辑把名称改成纯空白时页面返回 400 并
  指出名称有误，原名称、缺失来源及其他资料保持原样，本次填写的时长与说明
  留在错误页；只修正名称后再保存采用错误页里的填写，不新增曲目。正常曲库
  的收录、编辑与来源冲突行为继续保持兼容。
- 来源（PATCH source，直接提交 JSON）：source 是按文字维护的资料，请求
  里省略该字段时保留原值，只修改合法说明等资料返回 200 与原标识下的
  完整曲目，原来源逐字保留（含内部 LF/CRLF/CR 换行写法），其他版本
  共用同一来源也不能拒绝这种保存。明确提交空字符串、只有空格/制表符/
  换行的字符串或 JSON 的 null 时返回 400 与可读取的 JSON 错误，field
  指向 source，错误文字说明来源不能清空；数字、布尔值、数组或对象也
  返回 400，错误文字明确说明来源必须是字符串，数字不转成来源文字、
  false 不算未提交。失败请求即使同时带了合法的新名称、时长和说明也不
  保存其中任何一项：随后列表中目标记录的完整资料（中文说明、说明中的
  空行、标签文字与顺序）仍是提交前内容，记录数量与按标识升序的次序
  不变，同一来源的其他独立版本与无关曲目也不变。只有标识与名称、来源
  仍为 null 的旧记录：省略 source 同样允许编辑，响应与列表中的来源
  继续为 null；但旧记录明确提交空白来源或 null 仍按无效输入拒绝，不能
  与省略字段混为一谈。非法提交被拒后，向同一标识提交尚未被使用的合法
  来源可以正常更新；来源只裁掉整段首尾空白，内部空格与换行逐字保留；
  成功响应与列表读到的资料一致，失败请求中未再次提交的改动不会被补入。
- 时长（PATCH duration）：改成 0 或有限的非负小数时，成功响应中的时长
  与之后读取曲目列表得到的值一致，不做换算、舍入或自动纠错；只有明确
  提交 null 才把时长改成未知，0 仍然是已知的数字时长；只改名称或说明、
  省略 duration 时继续保留原时长（原本未知也继续未知）。每次成功都更新
  原标识、不新增记录，未提交的资料（含说明中的中文与换行）原样保留，
  列表顺序不变。
- 非法时长（负数、NaN/Infinity/溢出等非有限数值、字符串、布尔值、数组、
  对象）返回 400，field 指向 duration，错误信息说明时长有误；数字文字
  不自动转换成数字，false 不变成 0；同次请求里合法的新名称、新说明等
  也不会先写入，目标曲目完整资料仍与编辑前一致，其他曲目、记录数量与
  列表顺序都不受影响；原时长已知或未知适用相同拒绝规则。
- 一次非法时长编辑被拒后，用同一标识提交合法时长可正常保存；本次只
  提交时长时，失败请求里尝试修改的名称、说明不会被补入，本次明确提交
  的合法新资料则与时长一起保存。
- 标签（PATCH tags）：提交 tags 以本次标签整体替换原标签（不追加），
  成功返回 200 与完整曲目，随后读取列表得到相同的标签文字与顺序；
  各项去掉首尾空白、忽略空项、按完整文字首次出现去重，中文、项内空行
  与中英文逗号、顿号都是标签文字，不按行或标点拆分；多行标签与只写
  其中一行的标签仍是两项，仅换行写法（LF/CRLF）不同的两项不合并、
  各自保留提交的换行写法；省略 tags 保留原标签，明确提交空数组或
  null 则清空；只提交标签时名称、来源、时长、封面、说明原样保留；
  同一来源的多个独立版本互不影响，来源未改动不触发重复来源冲突。
  tags 为字符串/对象或数组中混入数字、布尔值、null 等非字符串项时
  返回 400 且 field=tags，整单失败，不保存同次请求中的任何部分内容。
- 说明（PATCH description，直接提交 JSON）：只提交 description 就更新原
  记录，返回 200 与修改后的完整资料，曲目标识不变，随后曲目列表接口读到
  的说明与成功响应一致。说明按提交原文逐字保存：中文、引号、尖括号、形似
  网页标签的文字、段落间连续空行以及首尾空格都是内容，不裁剪、不拆分、不
  替换；直接接口提交的 LF、CRLF、CR 换行写法各自保留，不套用网页编辑表单
  的换行统一规则。修改名称等其他合法资料但省略 description 时原说明完整
  保留；明确提交空字符串或 null 时保存为空字符串；只含空格、制表符或空行
  的字符串仍按原文保存、不能被当作空字符串——原本有文字、原本为空、原本
  只有空白的说明都遵守这些规则，修改后的响应与列表读取结果一致。只改说明
  时名称、来源、时长、封面、标签保留原值，记录数量与列表顺序不变；同一
  来源的多个独立版本中改一条的说明照常成功，其他版本的完整资料不受影响。
  description 误传数字、布尔值、数组或对象时返回 400，field 指向
  description，错误文字明确指出说明类型有误；即使同次请求还提交了合法的
  新名称或其他资料，也不能保存其中任何一部分，目标曲目与其他曲目的已保存
  资料都保持提交前内容；null 的清空含义不能混入这些类型错误，失败后列表
  仍看到原说明而不出现部分修改或额外记录。
- 名称（PATCH title，直接提交 JSON）：只提交 title 就更新原记录，返回 200
  与修改后的完整曲目，更新的仍是原来的标识；列表中该条记录的名称与完整
  资料和成功响应一致，不增加曲目，列表仍按标识升序。名称只去掉整段首尾
  空白，中文、引号、尖括号、内部连续空格与空行都是实际内容，按普通文字
  保存，不能被合并或删除；接口提交的内部 LF、CRLF 或单独 CR 换行各自按
  原文保存，不能因为网页编辑会统一换行就把接口输入也改写成 LF；用户确实
  修改名称内部文字或分行后，读回的名称包含本次改动。请求省略 title、只
  修改合法的说明等资料时，名称完整保留（包括原有的 LF/CRLF/CR 换行写法）；
  只提交新名称时则采用本次名称，来源、时长、封面、说明和标签保留原值。
  同一来源已有多个版本时，单独给其中一个版本改名照常成功，不误报来源
  冲突，其他版本的名称与完整资料不受影响；名称相同的不同曲目仍各自保持
  独立标识，改名不会把记录合并。名称为空字符串、只含空格、制表符或换行，
  或者提交 null、数字、布尔值、数组、对象时返回 400，field 指向 title，
  错误文字说明名称有误；即使同次请求还提交了合法的新说明，也不能先保存
  说明或其他部分内容，目标曲目与其他曲目的完整资料、数量及列表顺序都
  保持提交前的结果。
- 封面地址（PATCH cover_url，直接提交 JSON）：只提交 cover_url 就更新原
  记录，返回 200 与修改后的完整曲目，曲目标识、记录数量与列表原有次序
  不变，未提交的名称、来源、时长、说明和标签保留原值，随后列表读到的
  记录与成功响应一致。非空字符串只去掉整段文字的首尾空白：中文、引号、
  尖括号、内部空格、空行以及原有的 LF/CRLF/CR 换行写法都按文字逐字保留
  （接口不套用网页表单的换行归一），封面地址是一段资料，不拆成多个地址，
  也不因看起来不像网址而拒绝。只修改名称、时长等其他合法资料而省略
  cover_url 时，原封面地址完整保留：原来有地址（含内部换行写法）的不能
  被清空，原来为空的也继续为空。明确提交空字符串、仅含空格或换行的
  字符串或 JSON 的 null 都表示主动清空，成功后 cover_url 是空字符串而不是
  null，也不能继续返回旧地址；已有地址可以清空，原本没有地址的曲目同样
  接受这些提交，清空与同次提交的其他合法资料一起保存。同一来源的多个
  版本共用来源时，只改其中一条的封面地址照常成功，只影响选中的记录。
  cover_url 误传数字、布尔值、数组或对象时返回 400，field 指向 cover_url，
  错误文字明确指出封面地址类型有误；即使同次请求还提交了合法的新名称或
  时长，也不能保存其中一部分，目标曲目完整资料与其他曲目都保持提交前
  结果。封面地址合法但同次提交负数时长时整次拒绝，错误指向时长，原封面
  地址仍保留。
- 编辑页（GET/POST /tracks/{id}/edit）的标签每个标签项一个输入框：
  接口收录时按完整文字保存的标签（可含换行、中英文逗号、顿号）逐框展示，
  直接保存或仅改名称不拆不并不丢；增删改只影响对应框，裁剪、忽略空项、
  按完整文字首次出现去重、清空保存为空数组；其他字段非法导致保存失败时
  整条记录不变，本次填写的标签逐框回填，修正后保存回填内容。
- 标签原文含 CRLF/CR 换行时，未修改（或仅整项首尾增加空白）的框保存后
  保留该项原来的完整文字，仅换行写法不同的两项不被合并；确实修改的项
  按本次填写（LF）保存，其余项原文不变；失败重绘后修正再保存同样如此。
- 编辑页来源（GET/POST /tracks/{id}/edit）：来源框完整呈现已保存来源的
  内部文字、空格与分行；用户未改来源或仅增删首尾空白时保存其他资料，
  原来源（含 LF/CRLF/CR 换行写法）逐字节保留，仅内部换行写法不同的两段
  来源各自保留、不被合并；确实修改来源内部文字、空格或分行时按本次填写
  （换行统一为 LF）去掉首尾空白保存，与其他曲目完整文字相同仍拒绝并
  显示实际占用者；保存失败时本次填写的来源完整回填，修正后继续保存。
- 编辑页时长（GET/POST /tracks/{id}/edit 整表提交，时长以输入框文字
  连同其他资料一起提交）：打开时已知值按秒回填（整数不显示 .0、0 回填
  “0”），未知值输入框为空；改成 0 或 243.5 等有限非负数字文字保存成功
  后 303 回列表并提示修改成功，原标识不变，列表显示“0 秒/243.5 秒”，
  重新进入编辑页仍看到该值；数字写成文字是网页正常输入，不沿用 JSON
  接口拒绝字符串的结果。清空或只填空白保存为未知（duration 为 null，
  列表显示“未知”，编辑页仍为空），不会变成 0；原本未知也能正常补填，
  不会因原值为空被拒绝。只调时长时名称、来源、封面、说明（中文、空行、
  首尾空格）与标签（完整文字与先后）原样保留；同一来源的多个独立版本
  中只改一条时长时来源保留、保存成功，其他版本、记录数量与列表顺序
  不变。
- 编辑页时长无法解析为有限非负数（负数、普通文字、NaN、Infinity、1e999
  等）时返回 400，页面明确指出时长有误且时长框保留本次填写的文字；
  即使同次改了合法的名称或说明也整单失败，目标记录与其他曲目保持
  提交前状态，页面回填本次填写的全部内容；只修正时长再保存时，本次
  表单里的合法修改与时长一起写入，不会换回旧值。
- 编辑页名称（GET/POST /tracks/{id}/edit）：名称删空或只留空格、制表符
  时返回 400，页面与名称框旁都指出名称有误，不出现修改成功；无论来源
  保持原样还是改成尚未占用的来源，失败提示都指向名称。该曲目标识与全部
  已保存资料仍是提交前的内容，其他记录、数量与顺序不变；页面回填本次
  填写的名称、来源、时长、封面、说明与各个标签框（说明的中文、首尾空格
  与空行，标签项内的换行与逗号按各自输入边界保留，形似网页标签的文字
  仍是普通文字），不用原记录覆盖。只补上合法名称再保存时 303 回列表并
  显示修改成功与最新资料：名称只去掉首尾空白，中文、内部空格与标点保留，
  失败前填写的合法修改随名称一起保存，标识不变、不新增记录，重新打开
  编辑页与曲目列表读到的资料都与本次填写一致。同一来源已有多个版本时，
  来源框不动、只修正一条的名称照常保存成功，不触发来源冲突，其他版本
  的名称与资料保持原样。
- 编辑页名称的多行保留（GET/POST /tracks/{id}/edit）：名称框是多行
  输入框，接口收录的名称中的中文、内部空格、连续空行与各行文字打开
  页面时仍在原有位置（如“夜航”/空行/“现场  版”三行不会被并成一行），
  引号、尖括号与形似网页标签的文字一律转义为普通文字。只修改时长、
  说明等其他合法资料时名称原样保留：提交文字换行归一（CRLF/CR→LF）
  并去掉首尾空白后与原名称一致即视为未修改，原名称使用的 LF/CRLF/CR
  写法逐字节保留，仅首尾增删空白不算改动内部内容；确实修改名称文字、
  空格或分行时按本次填写保存（只裁整段首尾空白，内部空行与空格保留，
  换行统一为 LF），保存后重开编辑页与列表接口读到的结果一致。名称
  只剩空格、制表符、换行时返回 400 并在名称旁指出错误，整单不写入；
  名称合法但时长非法时同样 400 且不写入，错误页完整保留本次多行名称，
  只修正时长后保存采用错误页中的名称。首页收录表单的名称框同样支持
  多行，保存时换行统一为 LF。
- 请求体格式（PATCH /api/tracks/{id}）：目标曲目存在时，空请求体、缺少
  结尾的 JSON、夹有多余文字的 JSON、不能按 UTF-8 解码的请求内容都返回 400
  与可读取的 JSON 错误（“请求体不是有效的 JSON”），不出现连接突然断开或
  保存成功；能够解析成 JSON 但顶层是数组、字符串、数字、布尔值或 null 时也
  返回 400，但错误说明资料必须是 JSON 对象且 field 为 null，不把问题归给
  名称、时长等某个字段，也不保存其中的内容（数组不会当成标签、字符串不会
  当成名称）。两类 400 必须可由错误文字与 field 区分。失败后读取列表，目标
  曲目、同一来源的其他独立版本与其他曲目的标识、完整资料（含说明中的中文与
  空行、标签的完整文字和先后关系）、数量与次序都与提交前一致；被拒绝的编辑
  内容不会在后续合法请求中自动补入，实际保存只采用后一次请求明确提交的资料。
  不存在的普通数字标识：无法解析的请求体先返回 400 的 JSON 格式错误；请求体
  能解析时即使顶层不是对象也返回 404 并说明曲目不存在，不继续报告字段错误。
  对照：空对象 {} 返回 200 且原记录完整保留，与空请求体的 400 明确区分；提交
  部分资料返回 200 与更新后的完整曲目，只改变明确提交的字段。上述失败后列表
  仍能正常读取，已有曲目仍能接受合法编辑。

首页关键词查找（GET / 的 q 参数）：
- 名称、来源、说明或任一标签的完整文字包含关键词（连续文字，中文按原文、
  英文字母不区分大小写）即显示该曲目；不跨字段或跨标签拼接凑命中，封面
  地址与时长不参加搜索，百分号、下划线、引号、尖括号按普通文字查找并安全
  显示。关键词去掉首尾空白后使用并保留在查找框中，内部空格仍是搜索内容；
  留空或只含空白等同于不筛选。结果按标识升序，显示找到数量与曲库总数，
  沿用列表的资料展示与编辑入口；同名记录与同一来源的多个版本各自独立
  显示。只有名称的旧记录可按名称找到，缺失来源、空说明、空标签与页面
  占位提示都不产生命中。没有匹配结果时说明没有符合关键词的曲目并保留
  条件、提供清除入口；曲库为空时仍说明尚未收录曲目。重新打开带 q 的
  地址看到同样条件下的当前结果；搜索不改写任何曲目，曲目列表接口始终
  返回全部记录。

运行：python3 -m unittest test_app -v
"""
import html
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

APP = Path(__file__).resolve().parent / "app.py"

# 编辑页每个标签项渲染成一个同名 textarea，按文档先后顺序提交。
TAG_BOX_RE = re.compile(
    r'<textarea name="tags"[^>]*>(.*?)</textarea>', re.DOTALL
)
# 每个标签框配一个隐藏域，记录该框对应的原始标签序号（新增框为空）。
TAG_REF_RE = re.compile(
    r'<input type="hidden" name="tags_ref" value="(.*?)"'
)
TEXT_INPUT_RE_TEMPLATE = (
    r'<input type="text" id="f-{fid}" name="{name}"[^>]*?value="(.*?)"[^>]*?>'
)
DESCRIPTION_RE = re.compile(
    r'<textarea id="f-description" name="description">(.*?)</textarea>',
    re.DOTALL,
)
TITLE_RE = re.compile(
    r'<textarea id="f-title" name="title"[^>]*>(.*?)</textarea>',
    re.DOTALL,
)
SOURCE_RE = re.compile(
    r'<textarea id="f-source" name="source"[^>]*>(.*?)</textarea>',
    re.DOTALL,
)
COVER_RE = re.compile(
    r'<textarea id="f-cover-url" name="cover_url"[^>]*>(.*?)</textarea>',
    re.DOTALL,
)
BANNER_ERROR_RE = re.compile(
    r'<p class="banner error" role="alert">(.*?)</p>', re.DOTALL
)
BANNER_SUCCESS_RE = re.compile(
    r'<p class="banner success">(.*?)</p>', re.DOTALL
)
CONFLICT_BANNER_RE = re.compile(
    r'<div class="banner conflict"[^>]*>(.*?)</div>', re.DOTALL
)
CONFLICT_LIST_RE = re.compile(
    r'<ul class="conflict-list">(.*?)</ul>', re.DOTALL
)
CONFLICT_ITEM_RE = re.compile(
    r'<li><span class="track-id">#(\d+)</span>\s*(.*?)</li>', re.DOTALL
)
TRACK_LIST_RE = re.compile(r'<ol class="tracks">(.*?)</ol>', re.DOTALL)
TRACK_ITEM_RE = re.compile(
    r'<li id="track-(\d+)"[^>]*>.*?'
    r'<p class="track-title"><span class="track-id">#\d+</span>(.*?)</p>',
    re.DOTALL,
)
# 列表条目里“时长”一行的显示文字：数字时长为“N 秒/N.N 秒”，
# 未知或未填写时是带 unfilled 样式的“未知/未填写”占位。
TRACK_DURATION_LINE_RE = re.compile(
    r'<dt>时长</dt><dd>(.*?)</dd>', re.DOTALL
)
# 首页曲目列表中的整条记录（名称与各资料格都在这个 li 内）。名称与资料
# 输出前均经 HTML 转义，里面不会出现字面 </li>，非贪婪匹配即可安全分条。
TRACK_CARD_RE = re.compile(
    r'<li id="track-(\d+)"[^>]*>(.*?)</li>', re.DOTALL
)
# 一条记录资料区里的“字段名/字段值”配对；说明一格的 dd 带 class。
TRACK_CELL_RE = re.compile(
    r'<dt>(.*?)</dt>\s*<dd(?:\s[^>]*)?>(.*?)</dd>', re.DOTALL
)
UNFILLED_RE = re.compile(r'<span class="unfilled">(.*?)</span>', re.DOTALL)
TAG_SPAN_RE = re.compile(r'<span class="tag">(.*?)</span>', re.DOTALL)
FORCE_CHECKBOX_RE = re.compile(
    r'<input type="checkbox" id="f-force"[^>]*>'
)
FIELD_ERROR_RE = re.compile(r'<p class="field-error">(.*?)</p>', re.DOTALL)


def strip_tags(markup):
    return html.unescape(re.sub(r"<[^>]+>", "", markup)).strip()


def parse_tag_boxes(page):
    """按页面顺序提取编辑页每个标签输入框的文字（已还原 HTML 转义）。"""
    return [html.unescape(raw) for raw in TAG_BOX_RE.findall(page)]


def parse_tag_refs(page):
    """按页面顺序提取每个标签框对应的原始标签序号（新增框为空串）。"""
    return [html.unescape(raw) for raw in TAG_REF_RE.findall(page)]


def browser_newlines(text):
    """模拟浏览器提交 textarea：框内换行一律按 CRLF 编码。"""
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")


def parse_input_value(page, field_id, name):
    pattern = TEXT_INPUT_RE_TEMPLATE.format(fid=field_id, name=name)
    match = re.search(pattern, page, re.DOTALL)
    assert match is not None, f"页面中找不到字段 {name} 的输入框"
    return html.unescape(match.group(1))


def parse_description_box(page):
    """提取编辑页说明框在浏览器中呈现的文字（模拟 HTML 解析规则）。

    浏览器会忽略 textarea 起始标签后紧跟的第一个换行（CRLF 算作一个），
    并把标记中的 CRLF/CR 当作 LF；服务端需要补写开头换行来抵消该规则。
    """
    match = DESCRIPTION_RE.search(page)
    assert match is not None, "页面中找不到说明输入框"
    return textarea_browser_text(match.group(1))


def parse_source_box(page):
    """提取来源框在浏览器中呈现的文字（与说明框相同的 HTML 解析规则）。"""
    match = SOURCE_RE.search(page)
    assert match is not None, "页面中找不到来源输入框"
    return textarea_browser_text(match.group(1))


def parse_cover_box(page):
    """提取封面地址框在浏览器中呈现的文字（与说明框相同的 HTML 解析规则）。"""
    match = COVER_RE.search(page)
    assert match is not None, "页面中找不到封面地址输入框"
    return textarea_browser_text(match.group(1))


def parse_title_box(page):
    """提取名称框在浏览器中呈现的文字（与说明框相同的 HTML 解析规则）。"""
    match = TITLE_RE.search(page)
    assert match is not None, "页面中找不到名称输入框"
    return textarea_browser_text(match.group(1))


def textarea_browser_text(raw_inner):
    """把 textarea 标记内容还原成浏览器框内实际呈现的文字。"""
    inner = html.unescape(raw_inner)
    if inner.startswith("\r\n"):
        inner = inner[2:]
    elif inner.startswith(("\n", "\r")):
        inner = inner[1:]
    return inner.replace("\r\n", "\n").replace("\r", "\n")


def description_box_markup(page):
    """返回说明框 textarea 的整段标记，用于断言转义发生在该框内部。"""
    match = DESCRIPTION_RE.search(page)
    assert match is not None, "页面中找不到说明输入框"
    return match.group(0)


def duration_text(value):
    """与 app.duration_to_text 相同的表单回填文本。"""
    if value is None:
        return ""
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)


def parse_conflict_items(page):
    """提取冲突横幅中列出的 (id, title)，按页面顺序。"""
    banner = CONFLICT_BANNER_RE.search(page)
    assert banner is not None, "页面中没有来源冲突横幅"
    listing = CONFLICT_LIST_RE.search(banner.group(1))
    assert listing is not None, "冲突横幅中没有已有记录列表"
    return [
        (int(match.group(1)), strip_tags(match.group(2)))
        for match in CONFLICT_ITEM_RE.finditer(listing.group(1))
    ]


def parse_listed_tracks(page):
    """提取首页曲目列表中的 (id, title)，按页面（标识升序）顺序。"""
    match = TRACK_LIST_RE.search(page)
    assert match is not None, "页面中没有曲目列表"
    return [
        (int(item.group(1)), strip_tags(item.group(2)))
        for item in TRACK_ITEM_RE.finditer(match.group(1))
    ]


def parse_listed_durations(page):
    """提取首页列表中每条曲目的时长显示文字，按列表顺序。

    数字时长读成“0 秒”“243.5 秒”等；未知时长读成“未知”，
    旧记录（来源缺失）读成“未填写”。
    """
    listing = TRACK_LIST_RE.search(page)
    assert listing is not None, "页面中没有曲目列表"
    return [strip_tags(match.group(1))
            for match in TRACK_DURATION_LINE_RE.finditer(listing.group(1))]


def parse_listed_track_cards(page):
    """提取首页列表中每条曲目的完整资料格，按标识升序返回。

    返回 {id: {"title": str, "cells": {字段名: 原始 HTML}, "tags": [...]}}。
    标题为转义后的原文（含换行），未做 strip_tags，便于断言分行与
    引号、尖括号的转义；cells 保留各字段对应的 dd 内部标记，由
    parse_listed_fields 解读成占位或文字。
    """
    listing = TRACK_LIST_RE.search(page)
    assert listing is not None, "页面中没有曲目列表"
    cards = {}
    for card in TRACK_CARD_RE.finditer(listing.group(1)):
        track_id = int(card.group(1))
        body = card.group(2)
        title_match = re.search(
            r'<p class="track-title"><span class="track-id">#\d+</span>'
            r'(.*?)</p>',
            body,
            re.DOTALL,
        )
        assert title_match is not None, f"曲目 #{track_id} 缺少名称行"
        cells = {}
        for field_name, cell_html in TRACK_CELL_RE.findall(body):
            cells[strip_tags(field_name)] = cell_html
        tags = [
            html.unescape(raw) for raw in TAG_SPAN_RE.findall(body)
        ]
        cards[track_id] = {
            "title": html.unescape(title_match.group(1)),
            "cells": cells,
            "tags": tags,
        }
    return cards


def cell_text(cell_html):
    """解读一个资料格：未填写占位返回 ("placeholder", 文字)，否则
    返回 ("text", 去掉标签后的文字)。"""
    placeholder = UNFILLED_RE.search(cell_html)
    if placeholder is not None:
        return "placeholder", html.unescape(placeholder.group(1))
    return "text", strip_tags(cell_html)


def listed_field(cards, track_id, field_name):
    """读首页某条曲目某个资料格的解读结果 (kind, value)。"""
    return cell_text(cards[track_id]["cells"][field_name])



class Server:
    """在临时数据目录上启动一个真实服务进程，测试结束后关闭。

    seeded_rows 给定时，先在数据目录里建好旧版曲库的 tracks 表
    （只有 id、title 两列的旧表结构），写入这些“只有标识与名称”的
    旧记录，然后再启动服务——用于覆盖曲库在服务启动前就已存在、
    尚未保存来源、时长、封面地址、说明和标签的情况。
    """

    def __init__(self, *, seeded_rows=None):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        if seeded_rows is not None:
            self.seed_legacy_rows(seeded_rows)
        self._start()

    def seed_legacy_rows(self, rows):
        """在服务启动前按旧表结构写入只有标识与名称的旧记录。

        rows 为 (id, title) 序列：标识可显式指定，允许不从 1 开始、
        中间有空缺；表只有 id、title 两列，其余资料列一律不存在，
        由服务启动时的迁移补齐为缺失值，而不是由测试预先填写。
        """
        db = sqlite3.connect(self.data_dir / "sound-shelf.sqlite")
        try:
            db.execute(
                "CREATE TABLE tracks ("
                "id INTEGER PRIMARY KEY, title TEXT NOT NULL)"
            )
            db.executemany(
                "INSERT INTO tracks (id, title) VALUES (?, ?)", list(rows)
            )
            db.commit()
        finally:
            db.close()

    def _start(self):
        self.proc = subprocess.Popen(
            [
                sys.executable, str(APP), "serve",
                "--host", "127.0.0.1", "--port", "0",
                "--data-dir", str(self.data_dir),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("服务进程未能启动")
        self.base = line.split("listening on", 1)[1].strip()
        # 打印监听地址到真正接受连接之间可能有极短间隙，允许重试。
        deadline = time.monotonic() + 5
        while True:
            try:
                self.request("GET", "/health")
                return
            except ConnectionRefusedError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.05)

    def stop_process(self):
        """停止服务进程但保留数据目录，供重新打开同一曲库使用。"""
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc.stdout.close()

    def restart(self):
        """关闭并在同一数据目录上重新启动服务，模拟再次打开同一曲库。"""
        self.stop_process()
        self._start()

    def request(self, method, path, payload=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read()
                return resp.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            return exc.code, json.loads(raw) if raw else None

    def raw_request(self, method, path, body=None, content_type=None,
                    follow_redirects=True):
        """发起一次 HTTP 请求，返回 (status, headers, body_bytes)。"""
        headers = {}
        if content_type is not None:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(
            self.base + path, data=body, method=method, headers=headers,
        )
        if not follow_redirects:
            # 不跟随重定向：自定义 opener 拦截 3xx，保留状态码与 Location。
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *args, **kwargs):
                    return None

            opener = urllib.request.build_opener(NoRedirect)
            try:
                with opener.open(req) as resp:
                    return resp.status, resp.headers, resp.read()
            except urllib.error.HTTPError as exc:
                return exc.code, exc.headers, exc.read()
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    def raw_json(self, method, path, raw_text):
        """按原文发送 JSON 类请求体，用于 NaN/Infinity 等非标准 JSON 片段。

        Python 的 json.loads 接受 NaN/Infinity，因此这些片段到达服务端
        后应被时长校验拒绝，而不是被当成无效 JSON。
        """
        return self.raw_request(
            method, path, raw_text.encode("utf-8"),
            content_type="application/json",
        )

    def get_page(self, path):
        status, headers, raw = self.raw_request("GET", path)
        return status, headers, raw.decode("utf-8")

    def post_form(self, path, fields, *, follow_redirects=True):
        """按浏览器方式提交 application/x-www-form-urlencoded 表单。

        fields 为 [(name, value), ...]，同名 name 可出现多次（编辑页每个
        标签框一个 tags 字段）；CRLF 换行原样编码，服务端负责把框内换行
        归一化为 LF。
        """
        body = urlencode(fields, doseq=True).encode("utf-8")
        status, headers, raw = self.raw_request(
            "POST", path, body,
            content_type="application/x-www-form-urlencoded",
            follow_redirects=follow_redirects,
        )
        return status, headers, raw.decode("utf-8")

    def create_track(self, **fields):
        payload = {"title": "未命名", "source": "/default"}
        payload.update(fields)
        status, body = self.request("POST", "/api/tracks", payload)
        assert status == 201, f"准备数据失败：{status} {body}"
        return body

    def insert_legacy(self, title):
        """直接写入一条只有标识与名称、来源缺失的旧记录。"""
        db = sqlite3.connect(self.data_dir / "sound-shelf.sqlite")
        try:
            cursor = db.execute("INSERT INTO tracks (title) VALUES (?)", (title,))
            db.commit()
            return cursor.lastrowid
        finally:
            db.close()

    def list_tracks(self):
        status, body = self.request("GET", "/api/tracks")
        assert status == 200, f"读取列表失败：{status} {body}"
        return body["tracks"]

    def close(self):
        self.stop_process()
        self._tmp.cleanup()


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        self.server = self.make_server()
        self.addCleanup(self.server.close)

    def make_server(self, *, seeded_rows=None):
        """启动一个服务；seeded_rows 在启动前按旧表结构写入数据目录。"""
        return Server(seeded_rows=seeded_rows)

    def restart_server(self):
        """在同一数据目录上重新打开服务，返回新的监听基址。"""
        self.server.restart()
        return self.server.base

    def create_track(self, **fields):
        return self.server.create_track(**fields)

    def patch(self, track_id, payload):
        return self.server.request("PATCH", f"/api/tracks/{track_id}", payload)

    def patch_raw(self, track_id, raw_text):
        """发送原始 JSON 文本的 PATCH（用于 NaN/Infinity 等非标准片段）。"""
        status, _, raw = self.server.raw_json(
            "PATCH", f"/api/tracks/{track_id}", raw_text
        )
        return status, json.loads(raw) if raw else None

    def post_raw(self, raw_text):
        """发送原始 JSON 文本的 POST（用于 NaN/Infinity 等非标准片段）。

        Python 的 json.loads 接受 NaN/Infinity，因此这些片段到达服务端
        后应被时长校验拒绝，而不是被当成无效 JSON。
        """
        status, _, raw = self.server.raw_json("POST", "/api/tracks", raw_text)
        return status, json.loads(raw) if raw else None

    def list_tracks(self):
        return self.server.list_tracks()

    def track_by_id(self, track_id):
        for record in self.list_tracks():
            if record["id"] == track_id:
                return record
        self.fail(f"列表中找不到曲目 #{track_id}")

    # -- 编辑页（HTML 表单）-------------------------------------------------

    def get_edit_page(self, track_id):
        status, headers, page = self.server.get_page(f"/tracks/{track_id}/edit")
        self.assertEqual(status, 200, page[:500])
        return page

    def edit_form_fields(self, *, title=None, source=None, duration=None,
                         cover_url=None, description=None, tags=()):
        """构造一份编辑页表单字段（同名 tags 每个标签框一项）。

        省略的普通字段默认给空串，模拟浏览器会提交所有输入框；
        tags 为标签框文字的有序列表（可含 CRLF/LF 换行）。
        """
        fields = [
            ("title", "" if title is None else title),
            ("source", "" if source is None else source),
            ("duration", "" if duration is None else duration),
            ("cover_url", "" if cover_url is None else cover_url),
            ("description", "" if description is None else description),
        ]
        fields.extend(("tags", text) for text in tags)
        return fields

    def post_edit_form(self, track_id, fields, *, follow_redirects=False):
        return self.server.post_form(
            f"/tracks/{track_id}/edit", fields,
            follow_redirects=follow_redirects,
        )

    def submit_edit_form_and_open_listing(self, track_id, fields):
        """提交编辑表单：成功应 303 回列表；手动跟随 Location 打开列表页。

        返回 (location, listing_page)：location 为重定向目标，
        listing_page 为用户保存成功后实际看到的曲目列表页面。
        """
        status, headers, _ = self.post_edit_form(track_id, fields)
        self.assertEqual(status, 303, "保存应成功并 303 回列表")
        location = headers["Location"]
        status, _, listing_page = self.server.get_page(location)
        self.assertEqual(status, 200, listing_page[:500])
        return location, listing_page

    def edit_fields_from_rendered_page(self, page):
        """按编辑页当前回填内容重建一份可提交的整表字段（含标签与序号）。

        模拟用户在打开的页面上不改正文直接再次保存：普通输入框取回填值，
        说明框取浏览器实际呈现的文字，标签逐框连同原始序号隐藏域一起取回。
        """
        fields = [
            ("title", parse_title_box(page)),
            ("source", parse_source_box(page)),
            ("duration", parse_input_value(page, "duration", "duration")),
            ("cover_url", parse_cover_box(page)),
            ("description", parse_description_box(page)),
        ]
        for box, ref in zip(parse_tag_boxes(page), parse_tag_refs(page)):
            fields.append(("tags", box))
            fields.append(("tags_ref", ref))
        return fields

    def form_with_field(self, fields, name, value):
        """替换整表字段中的一个普通（单值）字段，其余字段与顺序保持不变。"""
        return [
            (field_name, value if field_name == name else field_value)
            for field_name, field_value in fields
        ]

    def assert_tag_boxes(self, page, expected):
        """逐框断言编辑页标签输入框的完整文字与先后顺序。"""
        boxes = parse_tag_boxes(page)
        self.assertEqual(
            boxes, expected,
            "标签框内容不一致：\n  实际=%r\n  期望=%r" % (boxes, expected),
        )

    def assert_form_values(self, page, *, title=None, source=None,
                           duration=None, cover_url=None, description=None):
        """断言编辑页各普通字段输入框的回填值。"""
        if title is not None:
            self.assertEqual(parse_title_box(page), title)
        if source is not None:
            self.assertEqual(parse_source_box(page), source)
        if duration is not None:
            self.assertEqual(
                parse_input_value(page, "duration", "duration"), duration
            )
        if cover_url is not None:
            self.assertEqual(parse_cover_box(page), cover_url)
        if description is not None:
            match = DESCRIPTION_RE.search(page)
            self.assertIsNotNone(match)
            self.assertEqual(html.unescape(match.group(1)), description)

    # -- 首页收录表单 -------------------------------------------------------

    def get_home(self):
        status, _, page = self.server.get_page("/")
        self.assertEqual(status, 200, page[:500])
        return page

    def create_form_fields(self, *, title="", source="", duration="",
                           cover_url="", description="", tags="",
                           save_as_new_version=False):
        """构造一份首页收录表单字段；save_as_new_version=True 时带上勾选框。"""
        fields = [
            ("title", title),
            ("source", source),
            ("duration", duration),
            ("cover_url", cover_url),
            ("description", description),
            ("tags", tags),
        ]
        # 浏览器只在勾选时提交 checkbox 字段（值固定为 1）。
        if save_as_new_version:
            fields.append(("save_as_new_version", "1"))
        return fields

    def post_create_form(self, fields, *, follow_redirects=False):
        return self.server.post_form(
            "/", fields, follow_redirects=follow_redirects,
        )

    def create_fields_from_rendered_page(self, page):
        """按首页收录表单当前回填内容重建一份可提交字段（含另存勾选）。

        模拟用户在失败重绘的页面上保留已填内容、只修正出错字段后再次
        保存：普通输入框取回填值，说明框取浏览器实际呈现的文字，
        勾选框按当前选中状态还原。
        """
        fields = [
            ("title", parse_title_box(page)),
            ("source", parse_source_box(page)),
            ("duration", parse_input_value(page, "duration", "duration")),
            ("cover_url", parse_cover_box(page)),
            ("description", parse_description_box(page)),
            ("tags", parse_input_value(page, "tags", "tags")),
        ]
        checkbox = FORCE_CHECKBOX_RE.search(page)
        if checkbox is not None and "checked" in checkbox.group(0):
            fields.append(("save_as_new_version", "1"))
        return fields



class SameSourceVersionsEditTest(ServerTestCase):
    """同一来源另存的多个版本：编辑其中一条不应被自己或来源未变挡住。"""

    def setUp(self):
        super().setUp()
        self.first = self.create_track(
            title="夜航·首版",
            source="/music/yehang.flac",
            duration=243.5,
            cover_url="https://img.example/yehang.png",
            description="首版说明",
            tags=["民谣", "现场"],
        )
        self.second = self.create_track(
            title="夜航·重制",
            source="/music/yehang.flac",
            duration=250,
            cover_url="https://img.example/yehang-remaster.png",
            description="重制说明",
            tags=["民谣", "重制"],
            save_as_new_version=True,
        )

    def test_edit_metadata_without_source_succeeds(self):
        status, body = self.patch(self.second["id"], {
            "title": "夜航·重制（修订）",
            "description": "新的说明\n保留换行",
            "tags": ["民谣", "重制", "2026"],
        })
        self.assertEqual(status, 200, body)
        # 返回修改后的完整记录，标识不变，来源不变。
        self.assertEqual(body, {
            "id": self.second["id"],
            "title": "夜航·重制（修订）",
            "source": "/music/yehang.flac",
            "duration": 250,
            "cover_url": "https://img.example/yehang-remaster.png",
            "description": "新的说明\n保留换行",
            "tags": ["民谣", "重制", "2026"],
        })

    def test_unsubmitted_fields_keep_old_values(self):
        status, body = self.patch(self.second["id"], {"title": "只改名称"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["duration"], 250)
        self.assertEqual(body["cover_url"], "https://img.example/yehang-remaster.png")
        self.assertEqual(body["description"], "重制说明")
        self.assertEqual(body["tags"], ["民谣", "重制"])
        self.assertEqual(body["source"], "/music/yehang.flac")

    def test_resubmit_current_source_succeeds(self):
        status, body = self.patch(self.first["id"], {
            "source": "/music/yehang.flac",
            "title": "夜航·首版（校对）",
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["id"], self.first["id"])
        self.assertEqual(body["source"], "/music/yehang.flac")
        self.assertEqual(body["title"], "夜航·首版（校对）")

    def test_source_differing_only_by_whitespace_counts_as_unchanged(self):
        status, body = self.patch(self.first["id"], {
            "source": "  /music/yehang.flac\t\n",
            "description": "首尾空白不算改来源",
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["source"], "/music/yehang.flac")
        self.assertEqual(body["description"], "首尾空白不算改来源")

    def test_other_version_untouched_and_no_merge_or_new_record(self):
        status, _ = self.patch(self.second["id"], {"title": "夜航·重制（修订）"})
        self.assertEqual(status, 200)

        tracks = self.list_tracks()
        # 记录数量不增加，两个版本仍然是各自独立的两条。
        self.assertEqual(len(tracks), 2)
        self.assertEqual([t["id"] for t in tracks],
                         [self.first["id"], self.second["id"]])
        # 列表能读到本次修改。
        self.assertEqual(self.track_by_id(self.second["id"])["title"],
                         "夜航·重制（修订）")
        # 另一版本的全部资料保持原样，没有被合并或覆盖。
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)


class EditSourceConflictTest(ServerTestCase):
    """把来源改成其他曲目已使用的文字：拒绝保存且不影响任何记录。"""

    def setUp(self):
        super().setUp()
        self.edited = self.create_track(
            title="待编辑",
            source="/music/edited.flac",
            duration=100,
            cover_url="https://img.example/edited.png",
            description="原始说明",
            tags=["原始"],
        )
        self.occupied_a = self.create_track(
            title="目标来源·版本一", source="/music/taken.flac", duration=1,
        )
        self.occupied_b = self.create_track(
            title="目标来源·版本二", source="/music/taken.flac", duration=2,
            save_as_new_version=True,
        )
        self.bystander = self.create_track(
            title="无关曲目", source="/music/other.flac",
        )

    def test_conflict_returns_409_with_all_occupants(self):
        status, body = self.patch(self.edited["id"], {
            "title": "合法的新名称",
            "source": "/music/taken.flac",
            "duration": 180,
            "description": "合法的新说明",
            "tags": ["合法", "标签"],
        })
        self.assertEqual(status, 409, body)
        self.assertEqual(body["field"], "source")
        # 目标来源的多个版本全部列出，按标识升序；
        # 不包含正在编辑的曲目，也不包含其他来源的记录。
        self.assertEqual(body["existing"], [
            {"id": self.occupied_a["id"], "title": "目标来源·版本一"},
            {"id": self.occupied_b["id"], "title": "目标来源·版本二"},
        ])

    def test_conflict_leaves_every_record_unchanged(self):
        status, _ = self.patch(self.edited["id"], {
            "title": "合法的新名称",
            "source": "/music/taken.flac",
            "duration": 180,
            "description": "合法的新说明",
            "tags": ["合法", "标签"],
        })
        self.assertEqual(status, 409)

        tracks = self.list_tracks()
        self.assertEqual(len(tracks), 4)
        # 正在编辑的记录仍是提交前的整条资料，没有保存一部分。
        self.assertEqual(self.track_by_id(self.edited["id"]), self.edited)
        # 目标来源的各条记录与无关记录都不受影响。
        self.assertEqual(self.track_by_id(self.occupied_a["id"]), self.occupied_a)
        self.assertEqual(self.track_by_id(self.occupied_b["id"]), self.occupied_b)
        self.assertEqual(self.track_by_id(self.bystander["id"]), self.bystander)

    def test_retry_with_free_source_saves_without_cancelling(self):
        status, _ = self.patch(self.edited["id"], {"source": "/music/taken.flac"})
        self.assertEqual(status, 409)

        # 不取消编辑、不另存版本，直接换成未收录的来源重新提交。
        status, body = self.patch(self.edited["id"], {
            "title": "合法的新名称",
            "source": "/music/fresh.flac",
            "duration": 180,
            "description": "合法的新说明",
            "tags": ["合法", "标签"],
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body, {
            "id": self.edited["id"],
            "title": "合法的新名称",
            "source": "/music/fresh.flac",
            "duration": 180,
            "cover_url": "https://img.example/edited.png",
            "description": "合法的新说明",
            "tags": ["合法", "标签"],
        })
        self.assertEqual(self.track_by_id(self.edited["id"]), body)

    def test_conflict_whitespace_trimmed_before_comparison(self):
        # 目标来源按去掉首尾空白后的文字判断。
        status, body = self.patch(self.edited["id"], {
            "source": "  /music/taken.flac  ",
        })
        self.assertEqual(status, 409, body)
        self.assertEqual(len(body["existing"]), 2)


class LegacyTrackEditTest(ServerTestCase):
    """只有标识与名称、来源缺失的旧记录的兼容行为。"""

    def setUp(self):
        super().setUp()
        self.legacy_a = self.server.insert_legacy("旧记录·甲")
        self.legacy_b = self.server.insert_legacy("旧记录·乙")
        self.normal = self.create_track(
            title="正常曲目", source="/music/normal.flac",
        )

    def test_legacy_edit_omitting_source_succeeds_and_stays_missing(self):
        status, body = self.patch(self.legacy_a, {
            "title": "旧记录·甲（补全）",
            "duration": 90,
            "description": "补写的说明",
            "tags": ["旧"],
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["id"], self.legacy_a)
        self.assertIsNone(body["source"])
        self.assertEqual(body["title"], "旧记录·甲（补全）")
        self.assertEqual(body["duration"], 90)
        # 另一条同样缺失来源的旧记录不构成冲突，也不受影响。
        other = self.track_by_id(self.legacy_b)
        self.assertIsNone(other["source"])
        self.assertEqual(other["title"], "旧记录·乙")

    def test_legacy_assigning_occupied_source_is_rejected(self):
        status, body = self.patch(self.legacy_a, {
            "source": "/music/normal.flac",
            "title": "不应保存的名称",
        })
        self.assertEqual(status, 409, body)
        self.assertEqual(body["field"], "source")
        self.assertEqual(body["existing"], [
            {"id": self.normal["id"], "title": "正常曲目"},
        ])
        # 拒绝后旧记录保持提交前的整条资料。
        record = self.track_by_id(self.legacy_a)
        self.assertIsNone(record["source"])
        self.assertEqual(record["title"], "旧记录·甲")

    def test_legacy_assigning_free_source_succeeds(self):
        status, body = self.patch(self.legacy_a, {
            "source": "/music/legacy-filled.flac",
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["source"], "/music/legacy-filled.flac")
        self.assertEqual(body["title"], "旧记录·甲")


class _EditSourceInvalidFixture(ServerTestCase):
    """非法来源编辑的共同夹具：资料丰富的目标曲目、同来源独立版本、
    无关曲目各一条；任何失败后整个列表都必须与提交前快照逐字一致。"""

    def setUp(self):
        super().setUp()
        # 目标曲目：说明含中文、段落间空行与结尾空行；标签含内部空格、
        # 中英文逗号与项内换行，标签的完整文字和先后关系都要保住。
        self.target = self.create_track(
            title="夜航",
            source="/music/yehang.flac",
            duration=243.5,
            cover_url="https://img.example/yehang.png",
            description="第一段说明\n\n第二段：含中文与标点！\n\n",
            tags=["民谣", "现场  录音", "逗号,标签", "多行\n标签"],
        )
        self.target_id = self.target["id"]
        # 同一来源的另一个独立版本：拒绝目标记录时它也必须保持原样。
        self.version_two = self.create_track(
            title="夜航（现场版）",
            source="/music/yehang.flac",
            duration=300,
            description="第二版说明\n\n版本二空行后的文字",
            tags=["版本二", "民谣"],
            save_as_new_version=True,
        )
        # 不同来源的无关曲目，用于核对数量、次序与其他记录不受影响。
        self.bystander = self.create_track(
            title="无关曲目",
            source="/music/other.flac",
            duration=7,
            description="其他来源的说明",
            tags=["其他"],
        )
        self.snapshot = self.list_tracks()
        self.snapshot_ids = [record["id"] for record in self.snapshot]

    def companion_payload(self):
        # 与非法来源同时提交的名称、时长、说明都合法：整单仍必须失败，
        # 其中任何一项都不能先保存。
        return {
            "title": "不应保存的新名称",
            "duration": 180,
            "description": "不应保存的新说明\n\n含空行与中文",
        }

    def assert_library_unchanged(self):
        tracks = self.list_tracks()
        # 记录数量与按标识升序的列表次序不变。
        self.assertEqual(len(tracks), len(self.snapshot))
        self.assertEqual(
            [record["id"] for record in tracks], self.snapshot_ids,
            "失败后曲目标识或次序发生变化",
        )
        # 目标记录的完整资料仍是提交前内容：中文说明、说明中的空行、
        # 标签文字与顺序都保留；同次请求里合法的新资料没有先写入。
        self.assertEqual(tracks, self.snapshot, "失败后曲目资料发生变化")
        # 同一来源的其他独立版本与无关曲目都不受影响。
        self.assertEqual(self.track_by_id(self.version_two["id"]), self.version_two)
        self.assertEqual(self.track_by_id(self.bystander["id"]), self.bystander)

    def patch_source_raw(self, raw_text):
        """按原始 JSON 字节发起一次 PATCH，用于核对错误是完整可读的 JSON。"""
        status, headers, body = self.server.raw_request(
            "PATCH", f"/api/tracks/{self.target_id}",
            body=raw_text.encode("utf-8"),
            content_type="application/json",
        )
        return status, headers, body

    def assert_readable_json_400(self, raw_text, *, fragment):
        status, headers, body = self.patch_source_raw(raw_text)
        self.assertEqual(status, 400, body)
        # 响应完整可读：Content-Type 是 JSON，Content-Length 与实际字节
        # 一致，体可以整体解析（连接没有被突然断开）。
        self.assertTrue(
            headers["Content-Type"].startswith("application/json"),
            headers["Content-Type"],
        )
        self.assertEqual(int(headers["Content-Length"]), len(body))
        parsed = json.loads(body.decode("utf-8"))
        self.assertEqual(parsed["field"], "source")
        self.assertIn("来源", parsed["error"])
        self.assertIn(fragment, parsed["error"])
        # 绝不是来源重复冲突的响应。
        self.assertNotIn("existing", parsed)
        return parsed


class EditSourceBlankOrNullRejectedTest(_EditSourceInvalidFixture):
    """明确提交空串、纯空白或 null 的来源：400 且说明来源不能清空。"""

    # 空字符串、只有空格、制表符或换行（含 CRLF/CR 与混合空白）。
    BLANK_VALUES = ("", " ", "  ", "\t", "\n", "\r", "\r\n", " \t\r\n ")

    def assert_blank_source_rejected(self, bad_source):
        payload = self.companion_payload()
        payload["source"] = bad_source
        status, body = self.patch(self.target_id, payload)
        self.assertEqual(status, 400, body)
        # field 指向 source，错误文字说明来源不能清空。
        self.assertEqual(body["field"], "source")
        self.assertIn("来源", body["error"])
        self.assertIn("不能清空", body["error"])
        # 绝不是来源重复冲突的响应。
        self.assertNotIn("existing", body)

    def test_empty_string_is_rejected(self):
        self.assert_blank_source_rejected("")
        self.assert_library_unchanged()

    def test_whitespace_only_sources_are_rejected(self):
        for bad in (" ", "  ", "\t", "\n", "\r", "\r\n", " \t\r\n "):
            with self.subTest(bad=repr(bad)):
                self.assert_blank_source_rejected(bad)
                self.assert_library_unchanged()

    def test_json_null_is_rejected(self):
        # 编辑来源没有“清空”语义：null 返回 400，而不是把来源置空。
        self.assert_blank_source_rejected(None)
        self.assert_library_unchanged()

    def test_blank_source_alone_is_rejected(self):
        # 请求里只有非法 source、不夹带其他字段时规则相同。
        status, body = self.patch(self.target_id, {"source": " \t\n"})
        self.assertEqual(status, 400, body)
        self.assertEqual(body["field"], "source")
        self.assertIn("不能清空", body["error"])
        self.assert_library_unchanged()

    def test_blank_source_with_more_valid_fields_saves_nothing(self):
        # 即使同时带有合法的新名称、时长、说明、封面和标签也整单失败。
        status, body = self.patch(self.target_id, {
            "source": None,
            "title": "不应保存的新名称",
            "duration": 180,
            "cover_url": "https://img.example/should-not-save.png",
            "description": "不应保存的新说明\n\n含空行与中文",
            "tags": ["不应保存的新标签"],
        })
        self.assertEqual(status, 400, body)
        self.assertEqual(body["field"], "source")
        self.assert_library_unchanged()
        # 再明确点名原说明仍在，而不是部分修改后的结果。
        record = self.track_by_id(self.target_id)
        self.assertEqual(
            record["description"], "第一段说明\n\n第二段：含中文与标点！\n\n"
        )
        self.assertEqual(
            record["tags"], ["民谣", "现场  录音", "逗号,标签", "多行\n标签"]
        )

    def test_error_is_complete_readable_json(self):
        parsed = self.assert_readable_json_400(
            '{"source": "  \\t\\n ", "title": "不应保存的新名称", '
            '"duration": 180, "description": "不应保存的新说明"}',
            fragment="不能清空",
        )
        self.assert_library_unchanged()
        self.assertIn("不能清空", parsed["error"])


class EditSourceNonStringTypeRejectedTest(_EditSourceInvalidFixture):
    """来源提交数字、布尔值、数组或对象：400 且明确要求字符串，不隐式转换。"""

    def assert_non_string_source_rejected(self, bad_source):
        payload = self.companion_payload()
        payload["source"] = bad_source
        status, body = self.patch(self.target_id, payload)
        self.assertEqual(status, 400, body)
        # field 指向 source，错误文字明确说明来源必须是字符串。
        self.assertEqual(body["field"], "source")
        self.assertIn("来源", body["error"])
        self.assertIn("必须是字符串", body["error"])
        # 绝不是来源重复冲突的响应。
        self.assertNotIn("existing", body)

    def test_numbers_are_rejected_without_coercion_to_text(self):
        # 数字不能转成来源文字（包括 0 和小数）；原来源仍是原字符串。
        for bad in (0, 1, 243, 243.5, -3):
            with self.subTest(bad=bad):
                self.assert_non_string_source_rejected(bad)
                self.assert_library_unchanged()
                self.assertEqual(
                    self.track_by_id(self.target_id)["source"],
                    "/music/yehang.flac",
                )

    def test_booleans_are_rejected_and_false_is_not_omission(self):
        # true/false 都不是字符串；false 不能当成“没有提交 source”。
        for bad in (False, True):
            with self.subTest(bad=bad):
                self.assert_non_string_source_rejected(bad)
                self.assert_library_unchanged()

    def test_array_and_object_are_rejected(self):
        for bad in ([], ["/music/yehang.flac"], {}, {"source": "/music/x"}):
            with self.subTest(bad=bad):
                self.assert_non_string_source_rejected(bad)
                self.assert_library_unchanged()

    def test_non_string_source_with_all_legal_fields_saves_nothing(self):
        status, body = self.patch(self.target_id, {
            "source": 123,
            "title": "不应保存的新名称",
            "duration": 180,
            "cover_url": "https://img.example/should-not-save.png",
            "description": "不应保存的新说明",
            "tags": ["不应保存的新标签"],
        })
        self.assertEqual(status, 400, body)
        self.assertEqual(body["field"], "source")
        self.assertIn("必须是字符串", body["error"])
        self.assert_library_unchanged()

    def test_string_that_looks_like_number_is_accepted_as_text(self):
        # 对照：数字 123 被拒绝，但字符串 "123" 是合法的来源文字，
        # 按原文保存，证明拒绝针对的是类型而不是“看起来像数字”。
        status, body = self.patch(self.target_id, {"source": 123})
        self.assertEqual(status, 400, body)
        self.assertEqual(body["field"], "source")
        self.assert_library_unchanged()

        status, body = self.patch(self.target_id, {"source": "123"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["source"], "123")
        self.assertEqual(self.track_by_id(self.target_id)["source"], "123")

    def test_error_is_complete_readable_json(self):
        parsed = self.assert_readable_json_400(
            '{"source": false, "title": "不应保存的新名称", '
            '"description": "不应保存的新说明"}',
            fragment="必须是字符串",
        )
        self.assert_library_unchanged()
        self.assertIn("必须是字符串", parsed["error"])


class EditSourceRejectionAmongVersionsTest(ServerTestCase):
    """同一来源已有多个独立版本：拒绝一条的非法来源不改其他版本与无关曲目。"""

    def setUp(self):
        super().setUp()
        self.first = self.create_track(
            title="夜航·首版",
            source="/music/yehang.flac",
            duration=243.5,
            description="首版说明\n\n首版空行后的文字",
            tags=["民谣", "首版"],
        )
        self.second = self.create_track(
            title="夜航·重制",
            source="/music/yehang.flac",
            duration=250,
            description="重制说明",
            tags=["重制"],
            save_as_new_version=True,
        )
        self.third = self.create_track(
            title="夜航·现场",
            source="/music/yehang.flac",
            duration=255,
            description="现场说明",
            tags=["现场"],
            save_as_new_version=True,
        )
        self.bystander = self.create_track(
            title="无关曲目", source="/music/other.flac", duration=9,
        )
        self.expected_ids = [
            self.first["id"], self.second["id"],
            self.third["id"], self.bystander["id"],
        ]

    def test_rejecting_one_version_changes_nothing_else(self):
        # 修改中间版本时明确提交 null 来源，连同合法新名称、时长、说明。
        status, body = self.patch(self.second["id"], {
            "source": None,
            "title": "不应保存的重制名称",
            "duration": 260,
            "description": "不应保存的重制说明",
        })
        self.assertEqual(status, 400, body)
        self.assertEqual(body["field"], "source")
        self.assertIn("不能清空", body["error"])

        tracks = self.list_tracks()
        # 数量与按标识升序的次序不变。
        self.assertEqual(len(tracks), 4)
        self.assertEqual([t["id"] for t in tracks], self.expected_ids)
        # 被拒绝的目标记录与其他两个同来源版本、无关曲目都保持原样。
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)
        self.assertEqual(self.track_by_id(self.second["id"]), self.second)
        self.assertEqual(self.track_by_id(self.third["id"]), self.third)
        self.assertEqual(self.track_by_id(self.bystander["id"]), self.bystander)

    def test_type_error_on_one_version_changes_nothing_else(self):
        # 同一场景的类型错误版本：来源传 false 不能被当作未提交而保存。
        status, body = self.patch(self.third["id"], {
            "source": False,
            "title": "不应保存的现场名称",
        })
        self.assertEqual(status, 400, body)
        self.assertEqual(body["field"], "source")
        self.assertIn("必须是字符串", body["error"])
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)
        self.assertEqual(self.track_by_id(self.second["id"]), self.second)
        self.assertEqual(self.track_by_id(self.third["id"]), self.third)
        self.assertEqual(self.track_by_id(self.bystander["id"]), self.bystander)
        self.assertEqual(
            [t["id"] for t in self.list_tracks()], self.expected_ids
        )


class EditSourceOmittedKeepsValueTest(ServerTestCase):
    """请求根本没有 source 字段：200、原标识下的完整曲目，原来源逐字保留。"""

    def test_omit_source_with_description_only_keeps_source_verbatim(self):
        # 来源含内部空格与 LF/CRLF/CR 换行写法，必须逐字节保留。
        source = "本地/夜航 现场.flac\r\n第二行\n第三段\r第四段  保留"
        track = self.create_track(
            title="夜航",
            source=source,
            duration=243.5,
            cover_url="https://img.example/yehang.png",
            description="原说明\n\n空行后的文字",
            tags=["民谣", "现场  录音"],
        )

        # 请求里根本没有 source 字段，只修改合法说明。
        status, body = self.patch(track["id"], {
            "description": "只改了说明\n第二行：中文",
        })
        self.assertEqual(status, 200, body)
        # 返回原标识下的完整曲目。
        self.assertEqual(body["id"], track["id"])
        # 原来源逐字保留，内部换行写法不被改写或裁剪。
        self.assertEqual(body["source"], source)
        self.assertEqual(body["title"], "夜航")
        self.assertEqual(body["duration"], 243.5)
        self.assertEqual(body["cover_url"], "https://img.example/yehang.png")
        self.assertEqual(body["description"], "只改了说明\n第二行：中文")
        self.assertEqual(body["tags"], ["民谣", "现场  录音"])
        # 成功响应与列表读到的资料一致；不新增记录、次序不变。
        self.assertEqual(self.track_by_id(track["id"]), body)
        self.assertEqual(len(self.list_tracks()), 1)

    def test_other_versions_sharing_source_do_not_block_omitted_edit(self):
        first = self.create_track(
            title="夜航·首版", source="/music/yehang.flac",
            description="首版说明",
        )
        second = self.create_track(
            title="夜航·重制",
            source="/music/yehang.flac",
            description="重制说明",
            save_as_new_version=True,
        )

        # 只改第二个版本的说明、省略 source：其他版本共用来源也不能
        # 因此拒绝保存，也不能误报来源冲突。
        status, body = self.patch(second["id"], {
            "description": "重制说明（校对）",
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["id"], second["id"])
        self.assertEqual(body["source"], "/music/yehang.flac")
        self.assertEqual(body["description"], "重制说明（校对）")
        self.assertNotIn("existing", body)
        # 两个版本仍是各自独立的两条，第一条与来源都不变。
        self.assertEqual(self.track_by_id(first["id"]), first)
        record = self.track_by_id(second["id"])
        self.assertEqual(record, body)
        self.assertEqual(
            [t["id"] for t in self.list_tracks()],
            [first["id"], second["id"]],
        )


class LegacySourceOmitVsSubmitTest(ServerTestCase):
    """来源仍为 null 的旧记录：省略 source 允许编辑；明确提交无效值仍拒绝。"""

    def setUp(self):
        super().setUp()
        self.legacy_id = self.server.insert_legacy("旧记录")
        self.normal = self.create_track(
            title="正常曲目", source="/music/normal.flac",
            description="不应受影响",
        )

    def test_omit_source_edits_normally_and_stays_null(self):
        status, body = self.patch(self.legacy_id, {
            "title": "旧记录（补全）",
            "duration": 42,
            "description": "补写的说明",
            "tags": ["旧"],
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["id"], self.legacy_id)
        # 响应与列表中的来源继续为 null，不补默认值、不判重。
        self.assertIsNone(body["source"])
        self.assertEqual(body["title"], "旧记录（补全）")
        self.assertEqual(body["duration"], 42)
        self.assertIsNone(self.track_by_id(self.legacy_id)["source"])
        # 正常曲目不受影响，数量与次序不变。
        self.assertEqual(self.track_by_id(self.normal["id"]), self.normal)
        self.assertEqual(
            [t["id"] for t in self.list_tracks()],
            [self.legacy_id, self.normal["id"]],
        )

    def test_null_submission_is_not_the_same_as_omission(self):
        # 先证明省略 source 可以正常保存且来源仍是 null。
        status, body = self.patch(self.legacy_id, {"description": "第一次说明"})
        self.assertEqual(status, 200, body)
        self.assertIsNone(body["source"])

        # 明确提交 null 则是无效输入，不能与省略字段混为一谈。
        status, body = self.patch(self.legacy_id, {
            "source": None,
            "description": "不应保存的说明",
        })
        self.assertEqual(status, 400, body)
        self.assertEqual(body["field"], "source")
        self.assertIn("不能清空", body["error"])
        record = self.track_by_id(self.legacy_id)
        self.assertIsNone(record["source"])
        # 失败请求里的说明没有写入，保留上一次成功的内容。
        self.assertEqual(record["description"], "第一次说明")

    def test_blank_sources_are_rejected_for_legacy_too(self):
        # 旧记录明确提交空白来源同样按无效输入拒绝。
        for bad in ("", " ", "\t", "\n", "\r\n", " \t\r\n "):
            with self.subTest(bad=repr(bad)):
                status, body = self.patch(self.legacy_id, {
                    "source": bad,
                    "title": "不应保存的名称",
                })
                self.assertEqual(status, 400, body)
                self.assertEqual(body["field"], "source")
                self.assertIn("不能清空", body["error"])
                record = self.track_by_id(self.legacy_id)
                self.assertIsNone(record["source"])
                self.assertEqual(record["title"], "旧记录")
        self.assertEqual(self.track_by_id(self.normal["id"]), self.normal)

    def test_non_string_types_are_rejected_for_legacy_too(self):
        # 数字、布尔值、数组、对象也拒绝；false 不算未提交。
        for bad in (0, 243.5, False, True, [], {}):
            with self.subTest(bad=repr(bad)):
                status, body = self.patch(self.legacy_id, {"source": bad})
                self.assertEqual(status, 400, body)
                self.assertEqual(body["field"], "source")
                self.assertIn("必须是字符串", body["error"])
                self.assertIsNone(self.track_by_id(self.legacy_id)["source"])


class EditSourceRetryAfterRejectionTest(ServerTestCase):
    """非法来源被拒后，同一标识提交未被使用的合法来源可正常更新。"""

    def setUp(self):
        super().setUp()
        self.target = self.create_track(
            title="夜航",
            source="/music/yehang.flac",
            duration=243.5,
            cover_url="https://img.example/yehang.png",
            description="第一段说明\n\n第二段：含中文与标点！\n\n",
            tags=["民谣", "现场  录音", "逗号,标签"],
        )
        self.target_id = self.target["id"]
        # 同一来源的另一版本：目标改来源后它继续使用原来源，不受影响。
        self.version_two = self.create_track(
            title="夜航（现场版）",
            source="/music/yehang.flac",
            duration=300,
            tags=["版本二"],
            save_as_new_version=True,
        )
        self.bystander = self.create_track(
            title="无关曲目", source="/music/other.flac",
        )

    def assert_failed_changes_not_saved(self, record):
        """失败请求里夹带的名称、时长、说明都不在记录中。"""
        self.assertEqual(record["title"], "夜航")
        self.assertEqual(record["duration"], 243.5)
        self.assertEqual(
            record["description"], "第一段说明\n\n第二段：含中文与标点！\n\n"
        )
        self.assertEqual(record["cover_url"], "https://img.example/yehang.png")
        self.assertEqual(record["tags"], ["民谣", "现场  录音", "逗号,标签"])

    def test_fresh_source_after_null_rejection_saves_with_trim(self):
        # 第一次尝试：合法的新名称、新时长、新说明 + null 来源，被拒绝。
        status, body = self.patch(self.target_id, {
            "source": None,
            "title": "失败请求里的新名称",
            "duration": 1,
            "description": "失败请求里的新说明",
        })
        self.assertEqual(status, 400, body)
        self.assertEqual(body["field"], "source")
        self.assertIn("不能清空", body["error"])
        self.assert_failed_changes_not_saved(self.track_by_id(self.target_id))

        # 改用尚未被使用的合法来源重新提交，只提交 source：
        # 整段首尾空白被裁掉，内部空格与 LF/CRLF 换行逐字保留。
        new_source = "  \t\n/music/fresh.flac\n内部  空格\r\n尾段  \r\n"
        status, body = self.patch(self.target_id, {"source": new_source})
        self.assertEqual(status, 200, body)
        self.assertEqual(
            body["source"], "/music/fresh.flac\n内部  空格\r\n尾段"
        )
        # 未再次提交的失败改动不会被补入，其他资料仍是编辑前的值。
        self.assert_failed_changes_not_saved(body)
        # 成功响应与列表读到的资料一致。
        self.assertEqual(self.track_by_id(self.target_id), body)
        # 其他版本继续使用原来源，无关曲目不变，数量与次序不变。
        self.assertEqual(
            self.track_by_id(self.version_two["id"]), self.version_two
        )
        self.assertEqual(self.track_by_id(self.bystander["id"]), self.bystander)
        self.assertEqual(
            [t["id"] for t in self.list_tracks()],
            [self.target_id, self.version_two["id"], self.bystander["id"]],
        )

    def test_fresh_source_after_type_rejection_saves(self):
        # 第一次尝试因来源传数字被拒（false 不能当作未提交的同类错误）。
        status, body = self.patch(self.target_id, {
            "source": 123,
            "title": "失败请求里的新名称",
        })
        self.assertEqual(status, 400, body)
        self.assertEqual(body["field"], "source")
        self.assertIn("必须是字符串", body["error"])
        self.assertEqual(self.track_by_id(self.target_id)["source"],
                         "/music/yehang.flac")

        # 明确提交未被使用的合法来源文字后正常更新；数字没有被转成文字。
        status, body = self.patch(self.target_id, {
            "source": "/music/another-fresh.flac",
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["source"], "/music/another-fresh.flac")
        # 失败请求里的新名称没有被补入。
        self.assertEqual(body["title"], "夜航")
        self.assertEqual(self.track_by_id(self.target_id), body)
        self.assertEqual(
            [t["id"] for t in self.list_tracks()],
            [self.target_id, self.version_two["id"], self.bystander["id"]],
        )


class EditDurationValidTest(ServerTestCase):
    """PATCH duration 改成合法值：响应与列表一致，0、小数、null 语义清楚。"""

    def setUp(self):
        super().setUp()
        # 说明含中文与换行，用来证明调整时长不影响其他资料。
        self.track = self.create_track(
            title="山涧晨曲",
            source="/music/shanjian.flac",
            duration=212,
            cover_url="https://img.example/shanjian.png",
            description="清晨山涧录音\n第二行：鸟鸣",
            tags=["纯音乐", "现场"],
        )
        self.track_id = self.track["id"]
        self.after = self.create_track(
            title="排在后面的曲目", source="/music/after.flac", duration=8,
        )

    def expected_with(self, duration):
        record = dict(self.track)
        record["duration"] = duration
        return record

    def assert_saved_duration(self, duration):
        record = self.track_by_id(self.track_id)
        self.assertEqual(record["duration"], duration)
        return record

    def test_change_to_decimal_response_matches_listed_record(self):
        # 有限的非负小数原样保存，不做换算或舍入；成功响应与之后读取
        # 列表得到的完整记录一致。
        status, body = self.patch(self.track_id, {"duration": 243.5})
        self.assertEqual(status, 200, body)
        self.assertEqual(body, self.expected_with(243.5))
        self.assertEqual(self.track_by_id(self.track_id), body)

    def test_change_to_integer_keeps_integer_shape(self):
        # 整数值在响应与列表中都按整数呈现（不变成 307.0 之类的形态）。
        status, body = self.patch(self.track_id, {"duration": 307})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["duration"], 307)
        self.assertIsInstance(body["duration"], int)
        self.assertEqual(self.track_by_id(self.track_id), body)

    def test_change_to_zero_is_known_duration_not_unknown(self):
        # 0 是合法的已知时长，不能被当成未知（null）。
        status, body = self.patch(self.track_id, {"duration": 0})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["duration"], 0)
        self.assertIsNotNone(body["duration"])
        self.assertIsInstance(body["duration"], int)
        self.assertEqual(self.track_by_id(self.track_id), body)

        # 零与名称、说明一起提交时也成立，其余资料不被改动。
        status, body = self.patch(self.track_id, {
            "title": "山涧晨曲（静音版）",
            "duration": 0,
            "description": "开头静音\n0 秒前奏",
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["duration"], 0)
        self.assertEqual(body["title"], "山涧晨曲（静音版）")
        self.assertEqual(body["description"], "开头静音\n0 秒前奏")
        self.assertEqual(self.track_by_id(self.track_id), body)

    def test_explicit_null_sets_unknown(self):
        # 只有明确提交 null 才把时长改成未知。
        status, body = self.patch(self.track_id, {"duration": None})
        self.assertEqual(status, 200, body)
        self.assertIsNone(body["duration"])
        self.assertEqual(self.track_by_id(self.track_id), body)

    def test_null_unknown_is_distinct_from_zero(self):
        # 先改成未知，再改成 0：0 必须读回为数字 0，而不是继续未知；
        # 再改回未知时读回必须是 null，而不是 0。
        status, body = self.patch(self.track_id, {"duration": None})
        self.assertEqual(status, 200)
        self.assertIsNone(self.track_by_id(self.track_id)["duration"])

        status, body = self.patch(self.track_id, {"duration": 0})
        self.assertEqual(status, 200)
        self.assertEqual(body["duration"], 0)
        self.assertEqual(self.track_by_id(self.track_id)["duration"], 0)

        status, body = self.patch(self.track_id, {"duration": None})
        self.assertEqual(status, 200)
        self.assertIsNone(self.track_by_id(self.track_id)["duration"])

    def test_omitting_duration_while_changing_title_keeps_duration(self):
        # 只改名称、没有提交 duration，原来的数字时长继续保留。
        status, body = self.patch(self.track_id, {"title": "山涧晨曲（改名）"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["duration"], 212)
        self.assertEqual(self.track_by_id(self.track_id), body)

    def test_omitting_duration_while_changing_description_keeps_duration(self):
        # 只改说明（中文与换行），时长与其他未提交资料都保留原值。
        new_description = "新的说明\n第二行中文，保留逗号"
        status, body = self.patch(self.track_id, {
            "description": new_description,
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["duration"], 212)
        self.assertEqual(body["description"], new_description)
        self.assertEqual(body["title"], "山涧晨曲")
        self.assertEqual(body["source"], "/music/shanjian.flac")
        self.assertEqual(body["cover_url"], "https://img.example/shanjian.png")
        self.assertEqual(body["tags"], ["纯音乐", "现场"])
        self.assertEqual(self.track_by_id(self.track_id), body)

    def test_changing_duration_keeps_unsubmitted_fields_including_chinese_text(self):
        # 调整时长时没有提交名称、说明等：这些资料（含中文、换行）原样保留。
        status, body = self.patch(self.track_id, {"duration": 260.25})
        self.assertEqual(status, 200, body)
        self.assertEqual(body, {
            "id": self.track_id,
            "title": "山涧晨曲",
            "source": "/music/shanjian.flac",
            "duration": 260.25,
            "cover_url": "https://img.example/shanjian.png",
            "description": "清晨山涧录音\n第二行：鸟鸣",
            "tags": ["纯音乐", "现场"],
        })
        self.assertEqual(self.track_by_id(self.track_id), body)

    def test_changing_duration_keeps_same_id_and_list_order_and_count(self):
        before_ids = [t["id"] for t in self.list_tracks()]
        status, body = self.patch(self.track_id, {"duration": 12.5})
        self.assertEqual(status, 200, body)
        # 成功更新原来的标识，不新增记录，列表顺序不变。
        self.assertEqual(body["id"], self.track_id)
        after_ids = [t["id"] for t in self.list_tracks()]
        self.assertEqual(after_ids, before_ids)


class EditDurationUnknownBaseTest(ServerTestCase):
    """原时长未知时，省略保留未知、合法值可改成已知。"""

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="未知时长曲目",
            source="/music/unknown.flac",
            duration=None,
            description="时长待补",
        )
        self.track_id = self.track["id"]

    def test_unknown_duration_is_read_back_as_null(self):
        record = self.track_by_id(self.track_id)
        self.assertIsNone(record["duration"])

    def test_omitting_duration_keeps_unknown(self):
        # 原本未知，只改名称、不提交 duration，仍然是未知。
        status, body = self.patch(self.track_id, {"title": "未知时长曲目（改名）"})
        self.assertEqual(status, 200, body)
        self.assertIsNone(body["duration"])
        self.assertEqual(body["title"], "未知时长曲目（改名）")
        self.assertEqual(body["description"], "时长待补")
        self.assertIsNone(self.track_by_id(self.track_id)["duration"])

    def test_setting_known_value_from_unknown_succeeds(self):
        status, body = self.patch(self.track_id, {"duration": 95.5})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["duration"], 95.5)
        self.assertEqual(self.track_by_id(self.track_id), body)

    def test_zero_from_unknown_is_zero_not_unknown(self):
        status, body = self.patch(self.track_id, {"duration": 0})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["duration"], 0)
        self.assertIsNotNone(body["duration"])
        self.assertEqual(self.track_by_id(self.track_id)["duration"], 0)


class EditDurationInvalidTest(ServerTestCase):
    """PATCH 提交非法时长：400 且 field=duration，整条资料与其他记录不变。"""

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="山涧晨曲",
            source="/music/shanjian.flac",
            duration=212,
            cover_url="https://img.example/shanjian.png",
            description="清晨山涧录音\n第二行：鸟鸣",
            tags=["纯音乐", "现场"],
        )
        self.track_id = self.track["id"]
        # 另一首曲目用于证明拒绝不会波及其他记录。
        self.bystander = self.create_track(
            title="无关曲目", source="/music/other.flac", duration=33.3,
            description="不应受影响",
        )

    def assert_duration_rejected(self, bad_duration):
        """非法时长（连同合法的新名称、新说明一起提交）必须整单失败。"""
        status, body = self.patch(self.track_id, {
            "title": "不应保存的新名称",
            "duration": bad_duration,
            "description": "不应保存的新说明\n第二行",
        })
        self.assertEqual(status, 400, body)
        # 错误信息说明时长有误，并由 field 指向 duration。
        self.assertEqual(body["field"], "duration")
        self.assertIn("时长", body["error"])

    def assert_everything_unchanged(self):
        tracks = self.list_tracks()
        # 没有新增或删除记录，顺序仍是标识升序。
        self.assertEqual(
            [t["id"] for t in tracks],
            [self.track_id, self.bystander["id"]],
        )
        # 目标曲目的完整资料仍与编辑前一致：同次请求里合法的新名称、
        # 新说明没有先写入。
        self.assertEqual(self.track_by_id(self.track_id), self.track)
        # 其他曲目也不受影响。
        self.assertEqual(self.track_by_id(self.bystander["id"]), self.bystander)

    def test_negative_numbers_are_rejected(self):
        for bad in (-1, -0.01, -243.5):
            with self.subTest(bad=bad):
                self.assert_duration_rejected(bad)
                self.assert_everything_unchanged()

    def test_numeric_strings_are_rejected_without_coercion(self):
        # 数字文字不能自动转换成数字。
        for bad in ("243", "243.5", "0", "-1", "", " 12 "):
            with self.subTest(bad=bad):
                self.assert_duration_rejected(bad)
                self.assert_everything_unchanged()

    def test_boolean_is_rejected_without_becoming_zero_or_one(self):
        # false 不能变成 0，true 也不能变成 1。
        for bad in (False, True):
            with self.subTest(bad=bad):
                self.assert_duration_rejected(bad)
                self.assert_everything_unchanged()

    def test_non_numeric_scalars_are_rejected(self):
        for bad in ("abc", "null", [], {}):
            with self.subTest(bad=bad):
                self.assert_duration_rejected(bad)
                self.assert_everything_unchanged()

    def test_non_finite_values_are_rejected(self):
        # NaN、Infinity、-Infinity 以及解析后溢出为 Infinity 的指数文字，
        # 都是非有限数值，不能保存（通过原始 JSON 文本发送）。
        for raw_fragment in ("NaN", "Infinity", "-Infinity", "1e999", "-1e999"):
            with self.subTest(raw=raw_fragment):
                status, body = self.patch_raw(
                    self.track_id,
                    '{"title": "不应保存的新名称", "duration": '
                    f'{raw_fragment}, "description": "不应保存的新说明"}}',
                )
                self.assertEqual(status, 400, body)
                self.assertEqual(body["field"], "duration")
                self.assertIn("时长", body["error"])
                self.assert_everything_unchanged()

    def test_invalid_duration_alone_is_rejected(self):
        # 即使同次请求没有夹带其他字段，拒绝规则相同。
        status, body = self.patch(self.track_id, {"duration": -9})
        self.assertEqual(status, 400, body)
        self.assertEqual(body["field"], "duration")
        self.assert_everything_unchanged()

    def test_zero_decimal_and_int_string_distinction(self):
        # 对照保障：合法的 0 通过，而字符串 "0" 被拒绝，二者不能混淆。
        status, body = self.patch(self.track_id, {"duration": 0})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["duration"], 0)

        # 把时长改回一个已知值后再试字符串，确保拒绝不依赖当前值。
        self.patch(self.track_id, {"duration": 212})
        status, body = self.patch(self.track_id, {"duration": "0"})
        self.assertEqual(status, 400, body)
        self.assertEqual(body["field"], "duration")
        record = self.track_by_id(self.track_id)
        self.assertEqual(record["duration"], 212)
        self.assertEqual(record["title"], self.track["title"])


class EditDurationInvalidFromUnknownTest(ServerTestCase):
    """原时长未知时，非法时长同样被拒绝，不能靠原值不同绕过校验。"""

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="未知时长曲目",
            source="/music/unknown.flac",
            duration=None,
            description="时长待补\n第二行",
        )
        self.track_id = self.track["id"]
        self.bystander = self.create_track(
            title="无关曲目", source="/music/other.flac", duration=33.3,
        )

    def test_invalid_durations_rejected_when_previously_unknown(self):
        cases = [
            ("dict", {"duration": -1}),
            ("dict", {"duration": "243"}),
            ("dict", {"duration": False}),
            ("dict", {"duration": True}),
            ("dict", {"duration": []}),
            ("raw", '{"duration": NaN}'),
            ("raw", '{"duration": Infinity}'),
            ("raw", '{"duration": -1e999}'),
        ]
        for kind, payload in cases:
            with self.subTest(payload=payload):
                if kind == "dict":
                    status, body = self.patch(self.track_id, {
                        "title": "不应从未知时长保存的名称",
                        **payload,
                    })
                else:
                    status, body = self.patch_raw(self.track_id, payload)
                self.assertEqual(status, 400, body)
                self.assertEqual(body["field"], "duration")
                self.assertIn("时长", body["error"])
                # 仍是编辑前的未知时长，名称等资料也没有写入，
                # 其他曲目不受影响。
                self.assertEqual(self.track_by_id(self.track_id), self.track)
                self.assertEqual(
                    self.track_by_id(self.bystander["id"]), self.bystander
                )
                self.assertEqual(
                    [t["id"] for t in self.list_tracks()],
                    [self.track_id, self.bystander["id"]],
                )


class EditDurationRetryAfterRejectionTest(ServerTestCase):
    """非法时长被拒后，用户修正输入继续编辑的结果。"""

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="山涧晨曲",
            source="/music/shanjian.flac",
            duration=212,
            cover_url="https://img.example/shanjian.png",
            description="原始说明\n保留换行",
            tags=["纯音乐"],
        )
        self.track_id = self.track["id"]
        self.bystander = self.create_track(
            title="无关曲目", source="/music/other.flac", duration=7,
        )

    def test_legal_retry_with_duration_only_saves_duration(self):
        # 第一次尝试：合法的新名称、新说明 + 非法时长，被拒绝。
        status, body = self.patch(self.track_id, {
            "title": "失败请求里的新名称",
            "duration": -5,
            "description": "失败请求里的新说明",
        })
        self.assertEqual(status, 400, body)
        self.assertEqual(body["field"], "duration")

        # 用同一标识只提交合法时长（没有重新提交名称或说明）：
        # 名称、说明保持编辑前的值，不会从失败请求中补入。
        status, body = self.patch(self.track_id, {"duration": 240})
        self.assertEqual(status, 200, body)
        self.assertEqual(body, {
            "id": self.track_id,
            "title": "山涧晨曲",
            "source": "/music/shanjian.flac",
            "duration": 240,
            "cover_url": "https://img.example/shanjian.png",
            "description": "原始说明\n保留换行",
            "tags": ["纯音乐"],
        })
        self.assertEqual(self.track_by_id(self.track_id), body)
        self.assertEqual(self.track_by_id(self.bystander["id"]), self.bystander)
        self.assertEqual(
            [t["id"] for t in self.list_tracks()],
            [self.track_id, self.bystander["id"]],
        )

    def test_legal_retry_with_new_metadata_saves_both(self):
        # 第一次尝试因字符串时长被拒（同时带了新名称、新说明）。
        status, body = self.patch(self.track_id, {
            "title": "失败请求里的新名称",
            "duration": "243.5",
            "description": "失败请求里的新说明\n换行",
        })
        self.assertEqual(status, 400, body)
        self.assertEqual(body["field"], "duration")
        self.assertEqual(self.track_by_id(self.track_id), self.track)

        # 本次明确提交合法的新名称、新说明与合法时长：一起保存本次内容。
        status, body = self.patch(self.track_id, {
            "title": "山涧晨曲（定稿）",
            "duration": 243.5,
            "description": "定稿说明\n第二行：鸟鸣",
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body, {
            "id": self.track_id,
            "title": "山涧晨曲（定稿）",
            "source": "/music/shanjian.flac",
            "duration": 243.5,
            "cover_url": "https://img.example/shanjian.png",
            "description": "定稿说明\n第二行：鸟鸣",
            "tags": ["纯音乐"],
        })
        self.assertEqual(self.track_by_id(self.track_id), body)
        # 仍然只有原来的两条记录，标识不变。
        self.assertEqual(
            [t["id"] for t in self.list_tracks()],
            [self.track_id, self.bystander["id"]],
        )

    def test_retry_with_null_after_rejection_sets_unknown(self):
        # 非法时长（false）被拒后，明确提交 null 可把时长改成未知；
        # 失败请求夹带的名称不补入。
        status, _ = self.patch(self.track_id, {
            "title": "失败请求里的新名称",
            "duration": False,
        })
        self.assertEqual(status, 400)

        status, body = self.patch(self.track_id, {"duration": None})
        self.assertEqual(status, 200, body)
        self.assertIsNone(body["duration"])
        self.assertEqual(body["title"], "山涧晨曲")
        self.assertEqual(body["description"], "原始说明\n保留换行")
        self.assertIsNone(self.track_by_id(self.track_id)["duration"])


class EditPageDurationBackfillTest(ServerTestCase):
    """打开编辑页：已知时长按秒回填文本，未知时长输入框为空。"""

    def test_known_integer_duration_backfills_as_seconds_text(self):
        track = self.create_track(
            title="已知整数时长", source="/music/known-int.flac", duration=212,
        )
        page = self.get_edit_page(track["id"])
        # 输入框按秒回填，整数不显示成 212.0。
        self.assert_form_values(page, duration="212")

    def test_known_decimal_duration_backfills_as_decimal_text(self):
        track = self.create_track(
            title="已知小数时长", source="/music/known-dec.flac", duration=243.5,
        )
        page = self.get_edit_page(track["id"])
        self.assert_form_values(page, duration="243.5")

    def test_zero_duration_backfills_as_zero_not_blank(self):
        track = self.create_track(
            title="零时长曲目", source="/music/zero.flac", duration=0,
        )
        page = self.get_edit_page(track["id"])
        # 0 是已知时长：框里必须回填 0，而不是像未知那样留空。
        self.assert_form_values(page, duration="0")

    def test_unknown_duration_backfills_as_empty_box(self):
        track = self.create_track(
            title="未知时长曲目", source="/music/unknown.flac", duration=None,
        )
        page = self.get_edit_page(track["id"])
        self.assert_form_values(page, duration="")


class EditPageDurationValidSaveTest(ServerTestCase):
    """编辑页表单把时长改成合法值：回列表提示成功，标识与显示都正确。

    网页接收的是输入框文字，数字写成文字提交是正常输入，不应沿用
    JSON 接口拒绝字符串的结果。
    """

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="山涧晨曲",
            source="/music/shanjian.flac",
            duration=212,
            cover_url="https://img.example/shanjian.png",
            description="清晨山涧录音",
            tags=["纯音乐"],
        )
        self.track_id = self.track["id"]
        # 另一首曲目用于证明编辑不改变记录数量与列表顺序。
        self.after = self.create_track(
            title="排在后面的曲目", source="/music/after.flac", duration=8,
        )

    def save_duration_via_form(self, duration_text, *, title="山涧晨曲"):
        fields = self.edit_form_fields(
            title=title,
            source="/music/shanjian.flac",
            duration=duration_text,
            cover_url="https://img.example/shanjian.png",
            description="清晨山涧录音",
            tags=["纯音乐"],
        )
        location, listing_page = self.submit_edit_form_and_open_listing(
            self.track_id, fields
        )
        return location, listing_page

    def assert_success_listing(self, location, listing_page):
        # 回到曲目列表并显示“修改成功”，且高亮的是原标识。
        self.assertEqual(
            location, f"/?highlight={self.track_id}&edited=1"
        )
        success = strip_tags(BANNER_SUCCESS_RE.search(listing_page).group(1))
        self.assertIn("修改成功", success)
        self.assertIn(f"#{self.track_id}", success)

    def test_change_to_zero_returns_to_listing_and_shows_zero_seconds(self):
        location, listing_page = self.save_duration_via_form("0")
        self.assert_success_listing(location, listing_page)
        # 原曲目标识不变；列表显示“0 秒”，而不是未知。
        self.assertEqual(
            parse_listed_tracks(listing_page),
            [(self.track_id, "山涧晨曲"), (self.after["id"], "排在后面的曲目")],
        )
        self.assertEqual(
            parse_listed_durations(listing_page), ["0 秒", "8 秒"]
        )
        record = self.track_by_id(self.track_id)
        self.assertEqual(record["duration"], 0)
        self.assertIsNotNone(record["duration"])
        # 重新进入编辑页仍能看到保存的值。
        self.assert_form_values(self.get_edit_page(self.track_id), duration="0")

    def test_change_to_decimal_text_saves_decimal(self):
        # 输入框文字 "243.5" 在网页表单里是正常输入，必须保存成 243.5。
        location, listing_page = self.save_duration_via_form("243.5")
        self.assert_success_listing(location, listing_page)
        self.assertEqual(
            parse_listed_durations(listing_page), ["243.5 秒", "8 秒"]
        )
        record = self.track_by_id(self.track_id)
        self.assertEqual(record["duration"], 243.5)
        self.assertIsInstance(record["duration"], float)
        self.assert_form_values(self.get_edit_page(self.track_id), duration="243.5")

    def test_integer_text_keeps_integer_shape(self):
        location, listing_page = self.save_duration_via_form("307")
        self.assert_success_listing(location, listing_page)
        self.assertEqual(
            parse_listed_durations(listing_page), ["307 秒", "8 秒"]
        )
        record = self.track_by_id(self.track_id)
        self.assertEqual(record["duration"], 307)
        self.assertIsInstance(record["duration"], int)
        self.assert_form_values(self.get_edit_page(self.track_id), duration="307")

    def test_text_numbers_surrounded_by_space_are_accepted(self):
        # 输入框首尾空白会被忽略；这与 JSON 接口直接拒绝字符串不同，
        # 是网页输入路径的正常行为。
        location, listing_page = self.save_duration_via_form("  243.5 ")
        self.assert_success_listing(location, listing_page)
        self.assertEqual(
            parse_listed_durations(listing_page), ["243.5 秒", "8 秒"]
        )
        self.assertEqual(self.track_by_id(self.track_id)["duration"], 243.5)
        self.assert_form_values(self.get_edit_page(self.track_id), duration="243.5")

    def test_decimal_forms_like_dot5_and_plus12_are_accepted(self):
        for typed, expected in ((".5", 0.5), ("+12", 12.0), ("0.0", 0)):
            with self.subTest(typed=typed):
                self.save_duration_via_form(typed)
                self.assertEqual(
                    self.track_by_id(self.track_id)["duration"], expected
                )
                # 恢复一个已知值，避免不同子例之间互相影响断言。
                self.save_duration_via_form("212")

    def test_record_count_and_list_order_unchanged_after_save(self):
        before = parse_listed_tracks(self.get_home())
        _, listing_page = self.save_duration_via_form("99.9")
        self.assertEqual(parse_listed_tracks(listing_page), before)
        self.assertEqual(
            [t["id"] for t in self.list_tracks()],
            [self.track_id, self.after["id"]],
        )


class EditPageDurationUnknownViaFormTest(ServerTestCase):
    """编辑页清空时长输入框：保存为未知（null），而不是 0。"""

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="山涧晨曲",
            source="/music/shanjian.flac",
            duration=212,
            cover_url="https://img.example/shanjian.png",
            description="清晨山涧录音",
            tags=["纯音乐", "现场"],
        )
        self.track_id = self.track["id"]
        self.after = self.create_track(
            title="排在后面的曲目", source="/music/after.flac", duration=8,
        )

    def fields_clearing_duration(self, duration_text):
        return self.edit_form_fields(
            title="山涧晨曲",
            source="/music/shanjian.flac",
            duration=duration_text,
            cover_url="https://img.example/shanjian.png",
            description="清晨山涧录音",
            tags=["纯音乐", "现场"],
        )

    def assert_now_unknown(self, listing_page):
        # 普通曲目（有来源）列表显示“未知”，不是“0 秒”也不是“未填写”。
        self.assertEqual(
            parse_listed_durations(listing_page), ["未知", "8 秒"]
        )
        record = self.track_by_id(self.track_id)
        self.assertIsNone(record["duration"])
        # 再次打开编辑页时长框仍为空。
        self.assert_form_values(self.get_edit_page(self.track_id), duration="")

    def test_empty_duration_box_sets_unknown_not_zero(self):
        location, listing_page = self.submit_edit_form_and_open_listing(
            self.track_id, self.fields_clearing_duration("")
        )
        self.assertEqual(
            location, f"/?highlight={self.track_id}&edited=1"
        )
        success = strip_tags(BANNER_SUCCESS_RE.search(listing_page).group(1))
        self.assertIn("修改成功", success)
        self.assert_now_unknown(listing_page)

    def test_whitespace_only_duration_box_sets_unknown(self):
        # 只填空白（空格、制表符及其组合）后保存同样视为清空：未知而不是 0。
        for typed in (" ", "\t", "  \t "):
            with self.subTest(typed=repr(typed)):
                # 先恢复成已知时长，再用仅含空白的输入框清空。
                status, _ = self.patch(self.track_id, {"duration": 212})
                self.assertEqual(status, 200)
                _, listing_page = self.submit_edit_form_and_open_listing(
                    self.track_id, self.fields_clearing_duration(typed)
                )
                self.assert_now_unknown(listing_page)

    def test_unknown_stays_unknown_when_reopened_and_resaved(self):
        # 清空保存为未知后，再打开编辑页直接保存：仍保持未知，不变成 0。
        self.submit_edit_form_and_open_listing(
            self.track_id, self.fields_clearing_duration("")
        )
        page = self.get_edit_page(self.track_id)
        status, headers, resp = self.post_edit_form(
            self.track_id, self.edit_fields_from_rendered_page(page)
        )
        self.assertEqual(status, 303, resp[:500])
        self.assertIsNone(self.track_by_id(self.track_id)["duration"])


class EditPageDurationFillFromUnknownTest(ServerTestCase):
    """原本未知的曲目在编辑页补填数字：不能因原值为空拒绝保存。"""

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="待补时长曲目",
            source="/music/fill-duration.flac",
            duration=None,
            cover_url="https://img.example/fill.png",
            description="时长待补\n第二行中文",
            tags=["待补"],
        )
        self.track_id = self.track["id"]

    def test_fill_decimal_from_unknown_succeeds(self):
        fields = self.edit_form_fields(
            title="待补时长曲目",
            source="/music/fill-duration.flac",
            duration="243.5",
            cover_url="https://img.example/fill.png",
            description="时长待补\n第二行中文",
            tags=["待补"],
        )
        location, listing_page = self.submit_edit_form_and_open_listing(
            self.track_id, fields
        )
        self.assertEqual(location, f"/?highlight={self.track_id}&edited=1")
        self.assertEqual(parse_listed_durations(listing_page), ["243.5 秒"])
        record = self.track_by_id(self.track_id)
        self.assertEqual(record["duration"], 243.5)
        self.assert_form_values(self.get_edit_page(self.track_id), duration="243.5")

    def test_fill_zero_from_unknown_succeeds(self):
        fields = self.edit_form_fields(
            title="待补时长曲目",
            source="/music/fill-duration.flac",
            duration="0",
        )
        location, listing_page = self.submit_edit_form_and_open_listing(
            self.track_id, fields
        )
        self.assertEqual(location, f"/?highlight={self.track_id}&edited=1")
        self.assertEqual(parse_listed_durations(listing_page), ["0 秒"])
        self.assertEqual(self.track_by_id(self.track_id)["duration"], 0)

    def test_resave_unknown_without_filling_keeps_unknown(self):
        # 打开原本未知的曲目，不填时长直接保存：仍是未知，不被拒绝。
        page = self.get_edit_page(self.track_id)
        status, headers, resp = self.post_edit_form(
            self.track_id, self.edit_fields_from_rendered_page(page)
        )
        self.assertEqual(status, 303, resp[:500])
        self.assertIsNone(self.track_by_id(self.track_id)["duration"])


class EditPageDurationKeepsMetadataTest(ServerTestCase):
    """只在编辑页调整时长：名称、来源、封面、说明与标签完整保留。"""

    DESCRIPTION = (
        "\n第一段说明：清晨山涧录音，逗号与中文保留\n\n"
        "  第二行首尾留空格  \n结尾空行在下一行\n"
    )
    TAGS = ["自然，雨声、溪流", "多行标签\n第二行", "现场"]

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="山涧晨曲",
            source="/music/shanjian.flac",
            duration=212,
            cover_url="https://img.example/shanjian.png",
            description=self.DESCRIPTION,
            tags=self.TAGS,
        )
        self.track_id = self.track["id"]

    def test_changing_only_duration_keeps_all_other_metadata(self):
        page = self.get_edit_page(self.track_id)
        # 从真实页面取回所有回填内容（说明含开头空行、首尾空格；标签逐框），
        # 只把时长改成 243.5，其余整表原样提交，换行按浏览器 CRLF 发送。
        fields = self.edit_fields_from_rendered_page(page)
        fields = self.form_with_field(fields, "duration", "243.5")
        fields = [
            (name, value.replace("\n", "\r\n"))
            if name in ("description", "tags") else (name, value)
            for name, value in fields
        ]
        location, listing_page = self.submit_edit_form_and_open_listing(
            self.track_id, fields
        )
        self.assertEqual(location, f"/?highlight={self.track_id}&edited=1")

        record = self.track_by_id(self.track_id)
        self.assertEqual(record["duration"], 243.5)
        # 名称、来源、封面原样保留。
        self.assertEqual(record["title"], "山涧晨曲")
        self.assertEqual(record["source"], "/music/shanjian.flac")
        self.assertEqual(record["cover_url"], "https://img.example/shanjian.png")
        # 说明中的中文、空行与首尾空格逐字保留（页面原样提交视为未改动）。
        self.assertEqual(record["description"], self.DESCRIPTION)
        # 标签完整文字与先后关系不变。
        self.assertEqual(record["tags"], self.TAGS)

        # 重新打开编辑页，说明框呈现与保存前一致，标签逐框一致。
        reopened = self.get_edit_page(self.track_id)
        self.assertEqual(parse_description_box(reopened), self.DESCRIPTION)
        self.assert_tag_boxes(reopened, self.TAGS + [""])
        self.assert_form_values(
            reopened,
            title="山涧晨曲",
            source="/music/shanjian.flac",
            duration="243.5",
            cover_url="https://img.example/shanjian.png",
        )

        # 列表页的说明文字也完整出现（含中文与空格）。
        self.assertIn("第一段说明：清晨山涧录音，逗号与中文保留", listing_page)


class EditPageDurationSameSourceVersionsTest(ServerTestCase):
    """同一来源已有多个独立版本：保留来源只改一条时长，其余版本不受影响。"""

    def setUp(self):
        super().setUp()
        self.first = self.create_track(
            title="夜航·首版",
            source="/music/yehang.flac",
            duration=243.5,
            description="首版说明",
            tags=["民谣"],
            save_as_new_version=True,
        )
        self.second = self.create_track(
            title="夜航·重制",
            source="/music/yehang.flac",
            duration=250,
            description="重制说明",
            tags=["重制"],
            save_as_new_version=True,
        )
        self.third = self.create_track(
            title="夜航·现场",
            source="/music/yehang.flac",
            duration=None,
            description="现场说明",
            tags=["现场"],
            save_as_new_version=True,
        )
        self.other = self.create_track(
            title="无关曲目", source="/music/other.flac", duration=9,
        )
        self.ordered_ids = [
            self.first["id"], self.second["id"],
            self.third["id"], self.other["id"],
        ]

    def test_edit_duration_of_one_version_keeps_source_and_others(self):
        # 编辑中间一条，来源文字保持不变，只把时长改成 300。
        fields = self.edit_form_fields(
            title="夜航·重制",
            source="/music/yehang.flac",
            duration="300",
            description="重制说明",
            tags=["重制"],
        )
        location, listing_page = self.submit_edit_form_and_open_listing(
            self.second["id"], fields
        )
        self.assertEqual(
            location, f"/?highlight={self.second['id']}&edited=1"
        )

        tracks = self.list_tracks()
        # 记录数量与列表顺序保持原样，标识没有增减。
        self.assertEqual([t["id"] for t in tracks], self.ordered_ids)
        self.assertEqual(parse_listed_tracks(listing_page), [
            (tid, title) for tid, title in zip(
                self.ordered_ids,
                ["夜航·首版", "夜航·重制", "夜航·现场", "无关曲目"],
            )
        ])
        # 被编辑的一条保存了新时长与原来源；其他版本各自保持提交前状态。
        self.assertEqual(self.track_by_id(self.second["id"]), {
            "id": self.second["id"],
            "title": "夜航·重制",
            "source": "/music/yehang.flac",
            "duration": 300,
            "cover_url": "",
            "description": "重制说明",
            "tags": ["重制"],
        })
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)
        self.assertEqual(self.track_by_id(self.third["id"]), self.third)
        self.assertEqual(self.track_by_id(self.other["id"]), self.other)

        # 列表时长显示按版本各自展示：未知版本仍显示“未知”。
        self.assertEqual(
            parse_listed_durations(listing_page),
            ["243.5 秒", "300 秒", "未知", "9 秒"],
        )

    def test_fill_unknown_version_duration_without_touching_others(self):
        # 给原本未知的第三个版本补填时长，同样保留来源且不影响其他版本。
        fields = self.edit_form_fields(
            title="夜航·现场",
            source="/music/yehang.flac",
            duration="305.25",
            description="现场说明",
            tags=["现场"],
        )
        status, headers, resp = self.post_edit_form(self.third["id"], fields)
        self.assertEqual(status, 303, resp[:500])
        self.assertEqual(
            self.track_by_id(self.third["id"])["duration"], 305.25
        )
        self.assertEqual(
            self.track_by_id(self.third["id"])["source"], "/music/yehang.flac"
        )
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)
        self.assertEqual(self.track_by_id(self.second["id"]), self.second)
        self.assertEqual(
            [t["id"] for t in self.list_tracks()], self.ordered_ids
        )


class EditPageDurationInvalidTest(ServerTestCase):
    """编辑页时长无法解析为有限非负数：400 并指出时长有误，输入原样保留。"""

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="山涧晨曲",
            source="/music/shanjian.flac",
            duration=212,
            cover_url="https://img.example/shanjian.png",
            description="原始说明\n第二行：鸟鸣",
            tags=["纯音乐", "现场"],
        )
        self.track_id = self.track["id"]
        self.bystander = self.create_track(
            title="无关曲目", source="/music/other.flac", duration=33.3,
        )

    def assert_duration_error_shown(self, page, typed):
        banner = BANNER_ERROR_RE.search(page)
        self.assertIsNotNone(banner)
        self.assertIn("时长", strip_tags(banner.group(1)))
        field_errors = [strip_tags(raw) for raw in FIELD_ERROR_RE.findall(page)]
        self.assertTrue(
            any("时长" in text for text in field_errors),
            f"时长字段旁应显示错误，实际：{field_errors}",
        )
        # 时长框保留本次填写的原文，便于继续编辑。
        self.assert_form_values(page, duration=typed)

    def test_bad_texts_return_400_and_keep_typed_text(self):
        # 注意："" 在单独的清空用例里是合法的未知语义；这里验证各种
        # 真正无法解析或为负/非有限的文字。
        for typed in ("-1", "-0.5", "-243.5", "abc", "时长",
                      "NaN", "Infinity", "-Infinity", "1e999",
                      "1e1000", "0x10", "1.2.3"):
            with self.subTest(typed=typed):
                fields = self.edit_form_fields(
                    title="山涧晨曲",
                    source="/music/shanjian.flac",
                    duration=typed,
                    cover_url="https://img.example/shanjian.png",
                    description="原始说明\n第二行：鸟鸣",
                    tags=["纯音乐", "现场"],
                )
                status, _, page = self.post_edit_form(self.track_id, fields)
                self.assertEqual(status, 400)
                self.assert_duration_error_shown(page, typed)
                # 原记录与其他曲目都保持提交前状态。
                self.assertEqual(self.track_by_id(self.track_id), self.track)
                self.assertEqual(
                    self.track_by_id(self.bystander["id"]), self.bystander
                )

    def test_invalid_duration_does_not_save_other_fields_in_same_form(self):
        # 同时改了合法的名称与说明：时长失败时这些资料不能先保存。
        fields = self.edit_form_fields(
            title="不应保存的新名称",
            source="/music/shanjian.flac",
            duration="abc",
            cover_url="https://img.example/new.png",
            description="本次填写的新说明\n开头空行\n".replace("\n", "\r\n"),
            tags=["纯音乐", "新标签"],
        )
        status, _, page = self.post_edit_form(self.track_id, fields)
        self.assertEqual(status, 400)
        self.assert_duration_error_shown(page, "abc")

        # 目标曲目完整资料仍是提交前的状态。
        self.assertEqual(self.track_by_id(self.track_id), self.track)
        # 其他曲目、记录数量与顺序都不受影响。
        self.assertEqual(
            [t["id"] for t in self.list_tracks()],
            [self.track_id, self.bystander["id"]],
        )
        self.assertEqual(
            self.track_by_id(self.bystander["id"]), self.bystander
        )

        # 页面回填本次填写的内容（不止时长），便于继续编辑。
        self.assert_form_values(
            page,
            title="不应保存的新名称",
            source="/music/shanjian.flac",
            duration="abc",
            cover_url="https://img.example/new.png",
        )
        self.assertEqual(
            parse_description_box(page), "本次填写的新说明\n开头空行\n"
        )
        self.assert_tag_boxes(page, ["纯音乐", "新标签", ""])

    def test_other_fields_reprinted_when_duration_is_negative(self):
        # 负数同样整单失败，名称与说明的本次填写内容也一起回填。
        fields = self.edit_form_fields(
            title="改名同时负数时长",
            source="/music/shanjian.flac",
            duration="-5",
            description="新说明第二版",
            tags=["纯音乐", "现场"],
        )
        status, _, page = self.post_edit_form(self.track_id, fields)
        self.assertEqual(status, 400)
        self.assert_duration_error_shown(page, "-5")
        self.assert_form_values(page, title="改名同时负数时长", duration="-5")
        self.assertEqual(parse_description_box(page), "新说明第二版")
        self.assertEqual(self.track_by_id(self.track_id), self.track)


class EditPageDurationRetryAfterFailureTest(ServerTestCase):
    """时长失败后只修正时长再次保存：本次表单里的合法修改一起写入。"""

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="山涧晨曲",
            source="/music/shanjian.flac",
            duration=212,
            cover_url="https://img.example/shanjian.png",
            description="原始说明\n第二行：鸟鸣",
            tags=["纯音乐"],
        )
        self.track_id = self.track["id"]
        self.bystander = self.create_track(
            title="无关曲目", source="/music/other.flac", duration=7,
        )

    def test_fix_only_duration_saves_reprinted_title_and_description(self):
        # 第一次：合法的新名称、新说明与非法时长一起提交，被 400 拒绝。
        new_description = "\n\n本次填写的说明\n开头空行保留\n"
        fields = self.edit_form_fields(
            title="山涧晨曲（定稿）",
            source="/music/shanjian.flac",
            duration="时长未知",
            cover_url="https://img.example/shanjian.png",
            description=new_description.replace("\n", "\r\n"),
            tags=["纯音乐", "定稿"],
        )
        status, _, failed_page = self.post_edit_form(self.track_id, fields)
        self.assertEqual(status, 400)
        # 失败没有写入任何资料。
        self.assertEqual(self.track_by_id(self.track_id), self.track)

        # 在回填页面上只修正时长，其余回填内容（名称、说明、标签）原样再提交。
        retry_fields = self.edit_fields_from_rendered_page(failed_page)
        retry_fields = self.form_with_field(retry_fields, "duration", "243.5")
        retry_fields = [
            (name, value.replace("\n", "\r\n"))
            if name in ("description", "tags") else (name, value)
            for name, value in retry_fields
        ]
        location, listing_page = self.submit_edit_form_and_open_listing(
            self.track_id, retry_fields
        )
        self.assertEqual(location, f"/?highlight={self.track_id}&edited=1")

        record = self.track_by_id(self.track_id)
        # 本次表单里填好的名称、说明与时长一起写入，没有换回旧值。
        self.assertEqual(record["title"], "山涧晨曲（定稿）")
        self.assertEqual(record["duration"], 243.5)
        self.assertEqual(record["description"], new_description)
        self.assertEqual(record["tags"], ["纯音乐", "定稿"])
        self.assertEqual(record["source"], "/music/shanjian.flac")
        self.assertEqual(record["cover_url"], "https://img.example/shanjian.png")
        # 其他曲目与记录数量不受影响。
        self.assertEqual(
            self.track_by_id(self.bystander["id"]), self.bystander
        )
        self.assertEqual(
            [t["id"] for t in self.list_tracks()],
            [self.track_id, self.bystander["id"]],
        )
        # 列表显示新时长；再次进入编辑页看到的是保存后的完整资料。
        self.assertEqual(
            parse_listed_durations(listing_page), ["243.5 秒", "7 秒"]
        )
        reopened = self.get_edit_page(self.track_id)
        self.assert_form_values(
            reopened, title="山涧晨曲（定稿）", duration="243.5"
        )
        self.assertEqual(parse_description_box(reopened), new_description)
        self.assert_tag_boxes(reopened, ["纯音乐", "定稿", ""])

    def test_fix_duration_without_resubmitting_old_metadata_still_keeps_it(self):
        # 第一次失败（名称改成新值、时长为 NaN 文字）。
        fields = self.edit_form_fields(
            title="只改了名称的尝试",
            source="/music/shanjian.flac",
            duration="NaN",
            cover_url="https://img.example/shanjian.png",
            description="原始说明\n第二行：鸟鸣",
            tags=["纯音乐"],
        )
        status, _, failed_page = self.post_edit_form(self.track_id, fields)
        self.assertEqual(status, 400)
        self.assertEqual(self.track_by_id(self.track_id), self.track)

        # 用户只修正时长后直接用回填整表保存：失败时填写的新名称仍随本次
        # 表单一起保存（不会被换回旧名称）。
        retry_fields = self.edit_fields_from_rendered_page(failed_page)
        retry_fields = self.form_with_field(retry_fields, "duration", "0")
        status, headers, resp = self.post_edit_form(self.track_id, retry_fields)
        self.assertEqual(status, 303, resp[:500])
        record = self.track_by_id(self.track_id)
        self.assertEqual(record["title"], "只改了名称的尝试")
        self.assertEqual(record["duration"], 0)
        self.assertEqual(record["description"], "原始说明\n第二行：鸟鸣")


class EditPageTitleRequiredTest(ServerTestCase):
    """编辑页名称删空或只剩空白：400 并指出名称有误，整次修改被拒绝。"""

    NEW_DESCRIPTION = (
        "\n第一段说明：清晨录音，中文与标点保留\n\n"
        "  第二行首尾留空格  \n结尾空行在下一行\n"
    )
    NEW_TAGS = ["自然，雨声、溪流", "多行标签\n第二行", "现场"]

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="山涧晨曲",
            source="/music/shanjian.flac",
            duration=212,
            cover_url="https://img.example/shanjian.png",
            description="原始说明\n第二行：鸟鸣",
            tags=["纯音乐", "现场"],
        )
        self.track_id = self.track["id"]
        self.bystander = self.create_track(
            title="无关曲目", source="/music/other.flac", duration=33.3,
        )

    def blank_title_fields(self, typed_title, *, source="/music/shanjian-v2.flac"):
        """名称删空/留白，其余资料都改成合法的新内容（换行按浏览器 CRLF）。"""
        return self.edit_form_fields(
            title=typed_title,
            source=source,
            duration="243.5",
            cover_url="https://img.example/new.png",
            description=self.NEW_DESCRIPTION.replace("\n", "\r\n"),
            tags=[tag.replace("\n", "\r\n") for tag in self.NEW_TAGS],
        )

    def assert_title_error_shown(self, page):
        # 页面明确指出名称有误，名称框旁也有对应提示，且不出现修改成功。
        banner = BANNER_ERROR_RE.search(page)
        self.assertIsNotNone(banner, "页面上应显示保存失败提示")
        self.assertIn("名称", strip_tags(banner.group(1)))
        field_errors = [strip_tags(raw) for raw in FIELD_ERROR_RE.findall(page)]
        self.assertTrue(
            any("名称" in text for text in field_errors),
            f"名称字段旁应显示错误，实际：{field_errors}",
        )
        self.assertIsNone(
            BANNER_SUCCESS_RE.search(page), "名称错误时不应出现修改成功"
        )

    def assert_library_unchanged(self):
        # 该曲目标识与全部已保存资料仍是提交前的内容；
        # 其他记录、数量与顺序都不变。
        tracks = self.list_tracks()
        self.assertEqual(
            [t["id"] for t in tracks], [self.track_id, self.bystander["id"]]
        )
        self.assertEqual(self.track_by_id(self.track_id), self.track)
        self.assertEqual(self.track_by_id(self.bystander["id"]), self.bystander)

    def test_empty_title_with_valid_changes_returns_400(self):
        # 用户从列表打开编辑页，删除名称，同时把其他资料改成合法的新内容。
        status, _, page = self.post_edit_form(
            self.track_id, self.blank_title_fields("")
        )
        self.assertEqual(status, 400)
        self.assert_title_error_shown(page)
        self.assert_library_unchanged()
        # 错误页的曲目列表里该曲目仍显示提交前的名称。
        self.assertEqual(parse_listed_tracks(page), [
            (self.track_id, "山涧晨曲"),
            (self.bystander["id"], "无关曲目"),
        ])

    def test_whitespace_only_titles_are_rejected(self):
        # 只留空格、制表符及其组合同样被拒绝；来源保持原样时也一样。
        for typed in (" ", "\t", "  \t "):
            with self.subTest(typed=repr(typed)):
                status, _, page = self.post_edit_form(
                    self.track_id,
                    self.blank_title_fields(
                        typed, source="/music/shanjian.flac"
                    ),
                )
                self.assertEqual(status, 400)
                self.assert_title_error_shown(page)
                self.assert_library_unchanged()

    def test_error_points_at_title_whether_source_kept_or_changed(self):
        # 来源保持原样、或改成尚未被占用的来源，失败提示都指出名称问题，
        # 而不是来源冲突。
        for source in ("/music/shanjian.flac", "/music/shanjian-v2.flac"):
            with self.subTest(source=source):
                status, _, page = self.post_edit_form(
                    self.track_id, self.blank_title_fields("", source=source)
                )
                self.assertEqual(status, 400)
                self.assert_title_error_shown(page)
                self.assertIsNone(CONFLICT_BANNER_RE.search(page))
                self.assert_library_unchanged()

    def test_failure_page_reprints_submission_not_original_record(self):
        status, _, page = self.post_edit_form(
            self.track_id, self.blank_title_fields("  \t ")
        )
        self.assertEqual(status, 400)
        self.assert_title_error_shown(page)

        # 名称框保留本次填写的空白原文，不被原记录的名称覆盖；
        # 来源、时长、封面也都回填本次填写的新内容。
        self.assert_form_values(
            page,
            title="  \t ",
            source="/music/shanjian-v2.flac",
            duration="243.5",
            cover_url="https://img.example/new.png",
        )
        # 说明框按本次填写还原：中文、开头空行、段落空行与首尾空格都在。
        self.assertEqual(parse_description_box(page), self.NEW_DESCRIPTION)
        # 每个标签框保留本次填写：项内换行与逗号、顿号按各自输入边界
        # 原样保留，末尾附一个空框。
        self.assert_tag_boxes(page, self.NEW_TAGS + [""])
        self.assert_library_unchanged()

    def test_html_looking_text_stays_plain_text_in_reprint(self):
        description = "说明里的 <b>加粗</b> 与 <em>斜体</em> 都是普通文字"
        tags = ["<script>alert(1)</script>", "正常，标签"]
        fields = self.edit_form_fields(
            title="",
            source="/music/shanjian.flac",
            duration="243.5",
            description=description,
            tags=tags,
        )
        status, _, page = self.post_edit_form(self.track_id, fields)
        self.assertEqual(status, 400)
        self.assert_title_error_shown(page)

        # 形似网页标签的文字按普通文字转义显示，不会变成页面元素。
        self.assertNotIn("<b>加粗</b>", page)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;b&gt;加粗&lt;/b&gt;", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        # 框内读回仍是用户填写的原文。
        self.assertEqual(parse_description_box(page), description)
        self.assert_tag_boxes(page, tags + [""])
        self.assert_library_unchanged()


class EditPageTitleRetryAfterFailureTest(ServerTestCase):
    """名称错误页上只补一个合法名称再保存：回填的合法修改随名称一起写入。"""

    NEW_DESCRIPTION = (
        "\n定稿说明：清晨录音，中文与标点保留\n\n"
        "  第二行首尾留空格  \n结尾空行在下一行\n"
    )
    NEW_TAGS = ["自然，雨声、溪流", "多行标签\n第二行", "现场"]

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="山涧晨曲",
            source="/music/shanjian.flac",
            duration=212,
            cover_url="https://img.example/shanjian.png",
            description="原始说明\n第二行：鸟鸣",
            tags=["纯音乐", "现场"],
        )
        self.track_id = self.track["id"]
        self.bystander = self.create_track(
            title="无关曲目", source="/music/other.flac", duration=7,
        )

    def submit_blank_title_form(self):
        """第一次保存：名称删空，其余资料都改成合法的新内容，被 400 拒绝。"""
        fields = self.edit_form_fields(
            title="",
            source="/music/shanjian-v2.flac",
            duration="243.5",
            cover_url="https://img.example/new.png",
            description=self.NEW_DESCRIPTION.replace("\n", "\r\n"),
            tags=[tag.replace("\n", "\r\n") for tag in self.NEW_TAGS],
        )
        status, _, page = self.post_edit_form(self.track_id, fields)
        self.assertEqual(status, 400)
        # 失败没有写入任何资料。
        self.assertEqual(self.track_by_id(self.track_id), self.track)
        return page

    def test_fix_only_title_saves_reprinted_metadata(self):
        failed_page = self.submit_blank_title_form()

        # 用户在错误页只补上一个合法名称（首尾带空白，检验只裁剪首尾；
        # 中文、内部空格与标点应保留），其余回填内容原样再次提交。
        retry_fields = self.edit_fields_from_rendered_page(failed_page)
        retry_fields = self.form_with_field(
            retry_fields, "title", "  山涧晨曲 · 定稿（2026）  "
        )
        retry_fields = [
            (name, value.replace("\n", "\r\n"))
            if name in ("description", "tags") else (name, value)
            for name, value in retry_fields
        ]
        location, listing_page = self.submit_edit_form_and_open_listing(
            self.track_id, retry_fields
        )
        self.assertEqual(location, f"/?highlight={self.track_id}&edited=1")

        # 回到曲目列表，显示修改成功与这条曲目的最新资料。
        success = strip_tags(BANNER_SUCCESS_RE.search(listing_page).group(1))
        self.assertIn("修改成功", success)
        self.assertIn(f"#{self.track_id}", success)
        self.assertEqual(parse_listed_tracks(listing_page), [
            (self.track_id, "山涧晨曲 · 定稿（2026）"),
            (self.bystander["id"], "无关曲目"),
        ])

        # 名称只去掉首尾空白；失败前那次填写中合法的修改（来源、时长、
        # 封面、说明、标签）随修正后的名称一起保存。
        record = self.track_by_id(self.track_id)
        self.assertEqual(record, {
            "id": self.track_id,
            "title": "山涧晨曲 · 定稿（2026）",
            "source": "/music/shanjian-v2.flac",
            "duration": 243.5,
            "cover_url": "https://img.example/new.png",
            "description": self.NEW_DESCRIPTION,
            "tags": self.NEW_TAGS,
        })
        # 成功更新原标识，不新建另一条曲目；其他曲目不受影响。
        self.assertEqual(
            [t["id"] for t in self.list_tracks()],
            [self.track_id, self.bystander["id"]],
        )
        self.assertEqual(self.track_by_id(self.bystander["id"]), self.bystander)

        # 重新打开编辑页，各字段与这次填写一致。
        reopened = self.get_edit_page(self.track_id)
        self.assert_form_values(
            reopened,
            title="山涧晨曲 · 定稿（2026）",
            source="/music/shanjian-v2.flac",
            duration="243.5",
            cover_url="https://img.example/new.png",
        )
        self.assertEqual(parse_description_box(reopened), self.NEW_DESCRIPTION)
        self.assert_tag_boxes(reopened, self.NEW_TAGS + [""])


class EditPageTitleSameSourceVersionsTest(ServerTestCase):
    """同一来源已有多个版本：来源框不动、只修正一条的名称，保存照常成功。"""

    def setUp(self):
        super().setUp()
        self.first = self.create_track(
            title="夜航·首版",
            source="/music/yehang.flac",
            duration=243.5,
            description="首版说明",
            tags=["民谣"],
        )
        self.second = self.create_track(
            title="夜航·重制",
            source="/music/yehang.flac",
            duration=250,
            description="重制说明",
            tags=["重制"],
            save_as_new_version=True,
        )
        self.ordered_ids = [self.first["id"], self.second["id"]]

    def test_rename_one_version_without_touching_source_succeeds(self):
        # 打开第二个版本的编辑页，来源框保持原样，只修正名称。
        page = self.get_edit_page(self.second["id"])
        fields = self.edit_fields_from_rendered_page(page)
        fields = self.form_with_field(fields, "title", "夜航·重制（更名）")
        location, listing_page = self.submit_edit_form_and_open_listing(
            self.second["id"], fields
        )
        self.assertEqual(location, f"/?highlight={self.second['id']}&edited=1")
        # 同来源本身不能让保存变成来源冲突：没有冲突横幅，直接修改成功。
        self.assertIsNone(CONFLICT_BANNER_RE.search(listing_page))
        success = strip_tags(BANNER_SUCCESS_RE.search(listing_page).group(1))
        self.assertIn("修改成功", success)
        self.assertEqual(parse_listed_tracks(listing_page), [
            (self.first["id"], "夜航·首版"),
            (self.second["id"], "夜航·重制（更名）"),
        ])

        # 只有这条的名称改变，来源不变；另一版本的名称与资料保持原样。
        record = self.track_by_id(self.second["id"])
        self.assertEqual(record["title"], "夜航·重制（更名）")
        self.assertEqual(record["source"], "/music/yehang.flac")
        self.assertEqual(record["duration"], 250)
        self.assertEqual(record["description"], "重制说明")
        self.assertEqual(record["tags"], ["重制"])
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)
        self.assertEqual(
            [t["id"] for t in self.list_tracks()], self.ordered_ids
        )


class EditPageMultilineTitleRenderTest(ServerTestCase):
    """打开编辑页：接口收录的多行名称逐行完整显示，特殊文字按普通文字。"""

    MULTILINE_TITLE = "夜航\n\n现场  版"

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title=self.MULTILINE_TITLE,
            source="/music/yehang.flac",
            duration=243.5,
            description="夜航现场录音",
            tags=["民谣"],
        )
        self.track_id = self.track["id"]

    def test_multiline_title_renders_line_by_line_in_title_box(self):
        page = self.get_edit_page(self.track_id)
        # 三行（含中间空行）都在原来的位置，不能并成“夜航现场  版”；
        # 中文、内部空格与各行文字完整保留。
        self.assertEqual(parse_title_box(page), self.MULTILINE_TITLE)
        self.assertIn("夜航\n\n现场  版", page)
        self.assertNotIn("夜航现场  版", page)
        self.assert_form_values(
            page,
            title=self.MULTILINE_TITLE,
            source="/music/yehang.flac",
            duration="243.5",
            description="夜航现场录音",
        )

    def test_crlf_and_cr_titles_render_with_same_lines(self):
        variants = (
            ("夜航\r\n\r\n现场  版", "/music/crlf.flac"),
            ("夜航\r现场  版", "/music/cr.flac"),
        )
        for raw, source in variants:
            with self.subTest(raw=raw):
                track = self.create_track(title=raw, source=source)
                page = self.get_edit_page(track["id"])
                # 浏览器把 CRLF/CR 都显示为换行：框内呈现相同的行与文字。
                self.assertEqual(
                    parse_title_box(page),
                    raw.replace("\r\n", "\n").replace("\r", "\n"),
                )

    def test_title_with_leading_text_and_blank_lines_keeps_them(self):
        # 收录规则会裁掉名称整段首尾空白，库里的名称不会以换行开头；
        # 首行之后的开头空行（连续空行）必须逐行保留。
        title = "夜航\n\n\n空三行后的名称"
        track = self.create_track(title=title, source="/music/blanks.flac")
        page = self.get_edit_page(track["id"])
        self.assertEqual(parse_title_box(page), title)

    def test_quotes_and_html_looking_title_is_shown_as_plain_text(self):
        title = (
            '夜航 “引号” 与 "双引号" 与 \'单引号\'\n'
            '<b>不是加粗</b> 与 <看起来像标签>\n'
            '</textarea><script>alert(1)</script>'
        )
        track = self.create_track(title=title, source="/music/escape.flac")
        page = self.get_edit_page(track["id"])
        # 框内读回仍是名称原文，没有被标签改变。
        self.assertEqual(parse_title_box(page), title)
        # 名称框标记内部一律转义，引号、尖括号不会变成页面元素。
        match = TITLE_RE.search(page)
        self.assertIn("&lt;b&gt;不是加粗&lt;/b&gt;", match.group(0))
        self.assertIn("&lt;/textarea&gt;", match.group(0))
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", match.group(0))
        # 引号同样转义，不能跳出属性或插入任何标记。
        self.assertIn("&quot;", match.group(0))
        self.assertIn("&#x27;", match.group(0))
        self.assertNotIn("<b>不是加粗</b>", match.group(0))
        self.assertNotIn("<script>alert(1)</script>", match.group(0))

    def test_listing_shows_title_lines(self):
        # 首页曲目列表中的名称同样按原有分行显示。
        _, _, home = self.server.get_page("/")
        self.assertEqual(
            parse_listed_tracks(home),
            [(self.track_id, self.MULTILINE_TITLE)],
        )


class EditPageMultilineTitleUntouchedSaveTest(ServerTestCase):
    """只改时长、说明等其他资料：多行名称（含 LF/CRLF/CR 写法）原样保留。"""

    LF_TITLE = "夜航\n\n现场  版\n结尾行"
    CRLF_TITLE = LF_TITLE.replace("\n", "\r\n")
    CR_TITLE = "夜航\r现场  版\r结尾行"

    def save_changing_only_metadata(self, track, **changes):
        """模拟浏览器：打开编辑页整表取回，框内换行按 CRLF 提交，只改其他资料。"""
        page = self.get_edit_page(track["id"])
        fields = self.edit_fields_from_rendered_page(page)
        fields = [
            (name, browser_newlines(value))
            if name in ("title", "source", "description", "tags")
            else (name, value)
            for name, value in fields
        ]
        for name, value in changes.items():
            fields = self.form_with_field(fields, name, value)
        return self.post_edit_form(track["id"], fields)

    def assert_title_preserved_when_other_fields_change(self, original_title):
        track = self.create_track(
            title=original_title,
            source="/music/yehang.flac",
            duration=243.5,
            description="原始说明",
            tags=["民谣"],
        )
        status, _, page = self.save_changing_only_metadata(
            track, duration="300", description="只改了说明与时长\n第二行"
        )
        self.assertEqual(status, 303, page[:500])
        record = self.track_by_id(track["id"])
        # 名称逐字节保留：换行写法不因浏览器显示与提交被改写。
        self.assertEqual(record["title"], original_title)
        self.assertEqual(record["duration"], 300)
        self.assertEqual(record["description"], "只改了说明与时长\n第二行")
        # 再次打开编辑页仍能看到完整多行名称。
        self.assertEqual(
            parse_title_box(self.get_edit_page(track["id"])),
            original_title.replace("\r\n", "\n").replace("\r", "\n"),
        )
        return record

    def test_lf_title_survives_browser_crlf_submission(self):
        record = self.assert_title_preserved_when_other_fields_change(
            self.LF_TITLE
        )
        self.assertNotIn("\r", record["title"])

    def test_crlf_title_survives_browser_crlf_submission(self):
        record = self.assert_title_preserved_when_other_fields_change(
            self.CRLF_TITLE
        )
        self.assertIn("\r\n", record["title"])

    def test_cr_title_survives_browser_crlf_submission(self):
        record = self.assert_title_preserved_when_other_fields_change(
            self.CR_TITLE
        )
        self.assertIn("\r", record["title"])
        self.assertNotIn("\r\n", record["title"])

    def test_repeated_resaves_keep_title_stable(self):
        track = self.create_track(
            title=self.CRLF_TITLE, source="/music/repeat.flac", duration=10
        )
        for round_index in range(2):
            status, _, page = self.save_changing_only_metadata(
                self.track_by_id(track["id"]), duration=str(20 + round_index)
            )
            self.assertEqual(status, 303, page[:500])
            self.assertEqual(
                self.track_by_id(track["id"])["title"], self.CRLF_TITLE
            )

    def test_surrounding_whitespace_only_counts_as_untouched(self):
        track = self.create_track(
            title=self.CRLF_TITLE, source="/music/pad.flac", duration=10
        )
        page = self.get_edit_page(track["id"])
        fields = self.edit_fields_from_rendered_page(page)
        # 只在名称首尾增删空白（含换行），内部文字与分行一字未动。
        padded = "  \r\n" + browser_newlines(self.LF_TITLE) + "\t \r\n"
        fields = self.form_with_field(fields, "title", padded)
        fields = self.form_with_field(fields, "duration", "11")
        status, _, resp = self.post_edit_form(track["id"], fields)
        self.assertEqual(status, 303, resp[:500])
        # 仍保留原名称的完整文字与 CRLF 写法，不按裁剪后的文字重写。
        self.assertEqual(self.track_by_id(track["id"])["title"], self.CRLF_TITLE)
        self.assertEqual(self.track_by_id(track["id"])["duration"], 11)

    def test_newline_style_variants_stay_two_distinct_records(self):
        # 两条曲目名称只在内部换行写法上不同：各自保留，打开编辑页再保存
        # 其他资料不会把它们变成同一个名称（名称不参与判重，这里只验证
        # 原文不被改写）。
        lf_track = self.create_track(title="夜航\n现场版", source="/music/lf.flac")
        crlf_track = self.create_track(
            title="夜航\r\n现场版", source="/music/crlf.flac"
        )
        status, _, page = self.save_changing_only_metadata(
            lf_track, duration="100"
        )
        self.assertEqual(status, 303, page[:500])
        status, _, page = self.save_changing_only_metadata(
            crlf_track, duration="200"
        )
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(self.track_by_id(lf_track["id"])["title"], "夜航\n现场版")
        self.assertEqual(
            self.track_by_id(crlf_track["id"])["title"], "夜航\r\n现场版"
        )

    def test_same_source_versions_edit_other_data_with_multiline_title(self):
        # 同一来源的多个版本，名称都是多行：只改一条的时长照常成功，
        # 另一版本的多行名称与全部资料保持原样。
        shared = "/music/yehang.flac"
        first = self.create_track(
            title="夜航\n\n首版", source=shared, duration=100
        )
        second = self.create_track(
            title="夜航\n\n现场  版", source=shared, duration=200,
            save_as_new_version=True,
        )
        status, _, page = self.save_changing_only_metadata(
            second, duration="201"
        )
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(
            self.track_by_id(second["id"])["title"], "夜航\n\n现场  版"
        )
        self.assertEqual(self.track_by_id(first["id"]), first)


class EditPageMultilineTitleChangesTest(ServerTestCase):
    """确实修改名称内部文字、空格或分行：按本次填写（LF）去掉首尾空白保存。"""

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="旧名称\n第二行",
            source="/music/yehang.flac",
            duration=243.5,
            description="原始说明",
        )
        self.track_id = self.track["id"]

    def submit_title(self, typed_title):
        page = self.get_edit_page(self.track_id)
        fields = self.edit_fields_from_rendered_page(page)
        fields = self.form_with_field(fields, "title", typed_title)
        return self.post_edit_form(self.track_id, fields)

    def test_edited_title_saved_with_lf_newlines_and_trimmed(self):
        # 用户改了名称内部文字与分行，浏览器按 CRLF 提交。
        typed = "  夜航\r\n\r\n现场  最终版\r\n "
        status, headers, page = self.submit_title(typed)
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(
            headers["Location"], f"/?highlight={self.track_id}&edited=1"
        )
        # 只去掉整段首尾空白；内部空行、行内双空格保留，换行统一为 LF。
        saved = "夜航\n\n现场  最终版"
        record = self.track_by_id(self.track_id)
        self.assertEqual(record["title"], saved)
        self.assertNotIn("\r", record["title"])
        # 其他资料保持原样，标识不变、不新增记录。
        self.assertEqual(record["source"], "/music/yehang.flac")
        self.assertEqual(record["duration"], 243.5)
        self.assertEqual(len(self.list_tracks()), 1)
        # 重新打开编辑页与列表接口读到的名称都与保存结果一致。
        self.assertEqual(parse_title_box(self.get_edit_page(self.track_id)), saved)
        _, _, listing = self.server.get_page("/")
        self.assertEqual(parse_listed_tracks(listing), [(self.track_id, saved)])

    def test_changing_only_line_breaks_saves_typed_layout(self):
        # 只调整分行（删掉空行、把一行拆成两行）也属于修改名称：
        # 按本次填写的分行（LF）保存。
        status, _, page = self.submit_title("旧名称第二行\r新拆的一行")
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(
            self.track_by_id(self.track_id)["title"], "旧名称第二行\n新拆的一行"
        )

    def test_changing_title_with_other_metadata_saves_both(self):
        page = self.get_edit_page(self.track_id)
        fields = self.edit_fields_from_rendered_page(page)
        fields = self.form_with_field(
            fields, "title", "夜航\n现场  版".replace("\n", "\r\n")
        )
        fields = self.form_with_field(fields, "duration", "300")
        status, headers, resp = self.post_edit_form(self.track_id, fields)
        self.assertEqual(status, 303, resp[:500])
        record = self.track_by_id(self.track_id)
        self.assertEqual(record["title"], "夜航\n现场  版")
        self.assertEqual(record["duration"], 300)


class EditPageMultilineTitleFailureTest(ServerTestCase):
    """名称空白或其他字段非法导致失败：多行名称完整回填，修正后采用回填值。"""

    MULTILINE_TITLE = "夜航\n\n现场  版"

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title=self.MULTILINE_TITLE,
            source="/music/yehang.flac",
            duration=243.5,
            description="原始说明",
            tags=["民谣"],
        )
        self.track_id = self.track["id"]

    def test_whitespace_only_multiline_title_returns_400(self):
        for typed in ("\n", " \n\t\n  ", "\t\n  \n"):
            with self.subTest(typed=repr(typed)):
                # 每条用例后重建曲目，避免前一次提交意外写入。
                fields = self.edit_form_fields(
                    title=browser_newlines(typed),
                    source="/music/yehang.flac",
                    duration="300",
                    description="想改说明",
                )
                status, _, page = self.post_edit_form(self.track_id, fields)
                self.assertEqual(status, 400)
                field_errors = [strip_tags(raw) for raw in FIELD_ERROR_RE.findall(page)]
                self.assertTrue(
                    any("名称" in text for text in field_errors),
                    f"名称字段旁应显示错误，实际：{field_errors}",
                )
                # 整条曲目不保存任何修改。
                self.assertEqual(self.track_by_id(self.track_id), self.track)
                # 名称框回填本次填写的空白换行（归一化为 LF），开头空行不丢。
                self.assertEqual(parse_title_box(page), typed)

    def test_bad_duration_keeps_multiline_title_then_fix_uses_reprint(self):
        # 第一次：合法的新多行名称与非法时长一起提交（换行按浏览器 CRLF）。
        new_title = "夜航\n\n现场  版（定稿）\n末行"
        fields = self.edit_form_fields(
            title=new_title.replace("\n", "\r\n"),
            source="/music/yehang.flac",
            duration="不是时长",
            description="原始说明",
            tags=["民谣"],
        )
        status, _, failed_page = self.post_edit_form(self.track_id, fields)
        self.assertEqual(status, 400)
        # 失败不写入任何资料，旧名称仍是提交前的内容。
        self.assertEqual(self.track_by_id(self.track_id), self.track)
        # 错误页完整保留本次填写的多行名称（分行不丢、不被旧值替换）。
        self.assertEqual(parse_title_box(failed_page), new_title)

        # 只修正时长：按错误页回填内容整表取回（框内换行浏览器按 CRLF 发送）。
        retry_fields = self.edit_fields_from_rendered_page(failed_page)
        retry_fields = self.form_with_field(retry_fields, "duration", "300")
        retry_fields = [
            (name, browser_newlines(value))
            if name in ("title", "source", "description", "tags")
            else (name, value)
            for name, value in retry_fields
        ]
        location, listing_page = self.submit_edit_form_and_open_listing(
            self.track_id, retry_fields
        )
        self.assertEqual(location, f"/?highlight={self.track_id}&edited=1")
        # 采用错误页中保留的多行名称（换行统一为 LF），不是旧名称。
        record = self.track_by_id(self.track_id)
        self.assertEqual(record["title"], new_title)
        self.assertEqual(record["duration"], 300)
        self.assertEqual(parse_listed_tracks(listing_page),
                         [(self.track_id, new_title)])
        self.assertEqual(
            parse_title_box(self.get_edit_page(self.track_id)), new_title
        )

    def test_failure_reprint_escapes_html_looking_title(self):
        title = '新名称\n<b>不是加粗</b>\n<img src="x">'
        fields = self.edit_form_fields(
            title=title.replace("\n", "\r\n"),
            source="/music/yehang.flac",
            duration="bad",
        )
        status, _, page = self.post_edit_form(self.track_id, fields)
        self.assertEqual(status, 400)
        self.assertEqual(parse_title_box(page), title)
        match = TITLE_RE.search(page)
        self.assertIn("&lt;b&gt;不是加粗&lt;/b&gt;", match.group(0))
        self.assertNotIn("<b>不是加粗</b>", match.group(0))
        # 失败后记录完全不动。
        self.assertEqual(self.track_by_id(self.track_id), self.track)


class HomeCreateMultilineTitleTest(ServerTestCase):
    """首页收录表单同样支持多行名称：保存为 LF，失败时完整回填。"""

    def test_multiline_title_created_via_form_is_saved_with_lf(self):
        title = "夜航\r\n\r\n现场  版\r\n结尾  "
        fields = self.create_form_fields(
            title=title,
            source="/音乐/夜航.flac",
            duration="243.5",
            description="首页收录\n第二行",
        )
        status, headers, _ = self.post_create_form(fields)
        self.assertEqual(status, 303, headers)
        tracks = self.list_tracks()
        self.assertEqual(len(tracks), 1)
        # 只裁掉首尾空白，内部空行与空格保留，换行统一为 LF。
        self.assertEqual(tracks[0]["title"], "夜航\n\n现场  版\n结尾")
        self.assertNotIn("\r", tracks[0]["title"])
        # 打开编辑页逐行可见。
        page = self.get_edit_page(tracks[0]["id"])
        self.assertEqual(
            parse_title_box(page), "夜航\n\n现场  版\n结尾"
        )

    def test_failed_create_reprints_multiline_title(self):
        # 时长非法导致失败：多行名称（含引号、尖括号）完整回填。
        title = '夜航\n现场  版\n<b>x</b>'
        fields = self.create_form_fields(
            title=title.replace("\n", "\r\n"),
            source="/music/x.flac",
            duration="非法时长",
        )
        status, _, page = self.post_create_form(fields)
        self.assertEqual(status, 400)
        self.assertEqual(parse_title_box(page), title)
        match = TITLE_RE.search(page)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", match.group(0))
        self.assertEqual(self.list_tracks(), [])
        # 只修正时长后保存，采用回填的多行名称。
        retry_fields = self.create_fields_from_rendered_page(page)
        retry_fields = self.form_with_field(retry_fields, "duration", "12")
        retry_fields = [
            (name, browser_newlines(value)) if name == "title" else (name, value)
            for name, value in retry_fields
        ]
        status, headers, _ = self.post_create_form(retry_fields)
        self.assertEqual(status, 303, headers)
        self.assertEqual(self.list_tracks()[0]["title"], title)


class EditPageTagBoxesTest(ServerTestCase):
    """打开编辑页：接口收录的标签逐项各占一个输入框，换行与标点原样保留。

    准备数据时标签同时覆盖：
    - 多行标签（两行分别为“自然”“雨声”）；
    - 与多行标签中某一行全文相同的独立标签（单独一项“雨声”）；
    - 含中文逗号、顿号等标点的完整标签（“晨间，鸟鸣、溪流”）。
    """

    MULTILINE_TAG = "自然\n雨声"
    SHARED_LINE_TAG = "雨声"
    PUNCT_TAG = "晨间，鸟鸣、溪流"
    INITIAL_TAGS = [MULTILINE_TAG, SHARED_LINE_TAG, PUNCT_TAG]

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="山涧晨曲",
            source="/music/shanjian.flac",
            duration=212,
            description="清晨山涧录音",
            tags=self.INITIAL_TAGS,
        )
        self.track_id = self.track["id"]

    def test_api_stored_tags_keep_full_text(self):
        # 前置保障：接口收录后三项按完整文字独立保存，顺序不变。
        self.assertEqual(self.track["tags"], self.INITIAL_TAGS)

    def test_edit_page_renders_one_box_per_tag_preserving_newlines(self):
        page = self.get_edit_page(self.track_id)
        # 三项已有标签各占一个框，末尾另有一个空框供新增；
        # 多行标签仍在同一个框内，不被换行拆开；标点完整保留。
        self.assert_tag_boxes(
            page,
            [self.MULTILINE_TAG, self.SHARED_LINE_TAG, self.PUNCT_TAG, ""],
        )
        # 页面正文必须真实包含多行文字的两行（而不是被并成一行）。
        self.assertIn("自然\n雨声", page)
        # 含标点的标签作为一个整体出现在同一个框内。
        self.assertIn("晨间，鸟鸣、溪流", page)
        # 其他字段也按当前资料回填。
        self.assert_form_values(
            page,
            title="山涧晨曲",
            source="/music/shanjian.flac",
            duration="212",
            description="清晨山涧录音",
        )

    def test_save_without_touching_tags_keeps_text_and_order(self):
        # 模拟用户打开编辑页：各框原样提交（框内换行以浏览器的 CRLF 发送），
        # 只把名称改成“山涧晨曲（定稿）”，不增删任何标签框。
        tags_crlf = [tag.replace("\n", "\r\n") for tag in self.INITIAL_TAGS]
        status, headers, _ = self.post_edit_form(
            self.track_id,
            self.edit_form_fields(
                title="山涧晨曲（定稿）",
                source="/music/shanjian.flac",
                duration="212",
                description="清晨山涧录音",
                tags=tags_crlf,
            ),
        )
        self.assertEqual(status, 303, headers)
        self.assertEqual(
            headers["Location"],
            f"/?highlight={self.track_id}&edited=1",
        )

        record = self.track_by_id(self.track_id)
        self.assertEqual(record["title"], "山涧晨曲（定稿）")
        # 三项标签的完整文字与先后顺序完全不变：多行标签没有被按行拆开，
        # 独立的“雨声”没有与多行标签合并，标点标签原样保留。
        self.assertEqual(record["tags"], self.INITIAL_TAGS)

        # 再次打开编辑页，页面内容与保存结果一致。
        page = self.get_edit_page(self.track_id)
        self.assert_tag_boxes(
            page,
            [self.MULTILINE_TAG, self.SHARED_LINE_TAG, self.PUNCT_TAG, ""],
        )
        self.assert_form_values(page, title="山涧晨曲（定稿）", duration="212")

    def test_save_changing_only_title_via_full_form_keeps_tags(self):
        # 即使标签框里带有首尾空白与 CRLF，保存时仅裁剪该项首尾空白，
        # 框内换行与标点保留；只改名称时标签结果与收录时一致。
        tags_with_ws = [
            "  " + self.MULTILINE_TAG.replace("\n", "\r\n") + "\t",
            " " + self.SHARED_LINE_TAG + " ",
            " " + self.PUNCT_TAG + " ",
        ]
        status, _, _ = self.post_edit_form(
            self.track_id,
            self.edit_form_fields(
                title="山涧晨曲·改名",
                source="/music/shanjian.flac",
                tags=tags_with_ws,
            ),
        )
        self.assertEqual(status, 303)
        self.assertEqual(self.track_by_id(self.track_id)["tags"],
                         self.INITIAL_TAGS)


class EditPageTagChangesTest(ServerTestCase):
    """编辑页上对标签的修改、增删、去重与清空的保存结果。"""

    A = "自然\n雨声"
    B = "雨声"
    C = "晨间，鸟鸣、溪流"

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="林间录音",
            source="/music/linjian.flac",
            duration=100,
            tags=[self.A, self.B, self.C],
        )
        self.track_id = self.track["id"]

    def save_tags(self, tags, **extra):
        fields = self.edit_form_fields(
            title="林间录音",
            source="/music/linjian.flac",
            duration="100",
            tags=tags,
            **extra,
        )
        status, headers, page = self.post_edit_form(self.track_id, fields)
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(
            headers["Location"], f"/?highlight={self.track_id}&edited=1"
        )
        return self.track_by_id(self.track_id)

    def test_editing_one_box_changes_only_that_tag(self):
        # 只修改第二个框（独立的“雨声”），其余两项文字与位置不变。
        record = self.save_tags([self.A, "雨声·加大声", self.C])
        self.assertEqual(record["tags"], [self.A, "雨声·加大声", self.C])

    def test_adding_and_removing_boxes_keeps_relative_order(self):
        # 在开头新增、中间删除（删掉独立的“雨声”）、末尾再新增：
        # 其余标签保持原先的相对先后关系。
        record = self.save_tags(["新增·开头", self.A, self.C, "新增·末尾"])
        self.assertEqual(
            record["tags"],
            ["新增·开头", self.A, self.C, "新增·末尾"],
        )

        # 再次打开页面逐框核对，末尾仍附空框。
        page = self.get_edit_page(self.track_id)
        self.assert_tag_boxes(
            page, ["新增·开头", self.A, self.C, "新增·末尾", ""]
        )

    def test_trim_blank_items_and_dedup_by_full_text(self):
        record = self.save_tags([
            "  " + self.A.replace("\n", "\r\n") + "  ",  # 去首尾空白后等于 A
            "",                                            # 空项忽略
            "   \r\n  ",                                   # 只有空白，忽略
            self.B,
            self.A,                                        # 与首项全文相同，去重
            "雨声\n自然",                                  # 行集合相同但顺序不同，保留
            self.C,
            " " + self.C + "\t",                           # 裁剪后与 C 相同，去重
        ])
        self.assertEqual(
            record["tags"],
            [self.A, self.B, "雨声\n自然", self.C],
        )
        # 共享某一行（“雨声”）的不同标签继续各自保留，互不合并。
        tags = record["tags"]
        self.assertIn(self.A, tags)
        self.assertIn(self.B, tags)
        self.assertIn("雨声\n自然", tags)

    def test_punctuation_inside_tag_is_never_a_separator(self):
        record = self.save_tags([
            "前奏，间奏、尾奏",
            "前奏",
            "一行写两样：风，雨、雷",
        ])
        self.assertEqual(
            record["tags"],
            ["前奏，间奏、尾奏", "前奏", "一行写两样：风，雨、雷"],
        )

    def test_clear_all_tags_saves_empty_array(self):
        record = self.save_tags([])
        self.assertEqual(record["tags"], [])

        # 再次打开编辑页只有一个空框，可以继续填写新标签。
        page = self.get_edit_page(self.track_id)
        self.assert_tag_boxes(page, [""])

        record = self.save_tags(["重新填写的标签", "第二个"])
        self.assertEqual(record["tags"], ["重新填写的标签", "第二个"])


class EditPageTagSaveFailureTest(ServerTestCase):
    """其他字段非法导致保存失败：记录不写入，标签逐框回填，修正后可保存。"""

    MULTILINE_TAG = "自然\n雨声"
    SHARED_LINE_TAG = "雨声"
    PUNCT_TAG = "晨间，鸟鸣、溪流"
    INITIAL_TAGS = [MULTILINE_TAG, SHARED_LINE_TAG, PUNCT_TAG]

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="山涧晨曲",
            source="/music/shanjian.flac",
            duration=212,
            description="清晨山涧录音",
            tags=self.INITIAL_TAGS,
        )
        self.track_id = self.track["id"]

    def test_negative_duration_blocks_save_and_reprints_every_tag_box(self):
        # 用户已修改标签（改一项、新增一项，框内换行以 CRLF 提交），
        # 但把时长误填成负数。
        edited_tags_lf = ["自然\n风声", self.SHARED_LINE_TAG, self.PUNCT_TAG,
                          "新增标签\n第二行"]
        edited_tags_crlf = [t.replace("\n", "\r\n") for t in edited_tags_lf]
        fields = self.edit_form_fields(
            title="山涧晨曲",
            source="/music/shanjian.flac",
            duration="-5",
            description="清晨山涧录音",
            tags=edited_tags_crlf,
        )
        status, headers, page = self.post_edit_form(self.track_id, fields)
        self.assertEqual(status, 400)

        # 页面明确指出时长错误。
        banner = BANNER_ERROR_RE.search(page)
        self.assertIsNotNone(banner)
        self.assertIn("时长", strip_tags(banner.group(1)))
        field_errors = [strip_tags(raw) for raw in FIELD_ERROR_RE.findall(page)]
        self.assertTrue(
            any("时长" in text for text in field_errors),
            f"时长字段旁应显示错误，实际：{field_errors}",
        )

        # 本次曲目的任何资料都没有写入：记录与提交前完全一致。
        self.assertEqual(self.track_by_id(self.track_id), self.track)

        # 用户填写的每项标签逐框回填：项内换行归一化为 LF 保留，
        # 项与项之间的边界不被拆开或合并，顺序不变；末尾附空框。
        self.assert_tag_boxes(page, edited_tags_lf + [""])
        # 出错的时长也回填用户填写的内容，便于修正。
        self.assert_form_values(page, duration="-5")

    def test_fix_duration_after_failure_saves_reprinted_tags(self):
        # 第一次保存：负数时长失败。
        edited_tags_lf = ["自然\n风声", self.SHARED_LINE_TAG, self.PUNCT_TAG,
                          "新增标签\n第二行"]
        edited_tags_crlf = [t.replace("\n", "\r\n") for t in edited_tags_lf]
        status, _, failed_page = self.post_edit_form(
            self.track_id,
            self.edit_form_fields(
                title="山涧晨曲",
                source="/music/shanjian.flac",
                duration="-5",
                description="清晨山涧录音",
                tags=edited_tags_crlf,
            ),
        )
        self.assertEqual(status, 400)

        # 从失败页面逐框取回回填的标签（连同末尾空框），仅把时长修正为正数
        # 后再次保存——模拟用户在回填页面上直接重试。
        reprinted_boxes = parse_tag_boxes(failed_page)
        self.assertEqual(reprinted_boxes, edited_tags_lf + [""])
        status, headers, page = self.post_edit_form(
            self.track_id,
            self.edit_form_fields(
                title="山涧晨曲",
                source="/music/shanjian.flac",
                duration="240",
                description="清晨山涧录音",
                # 回填文字中的 LF 再次按浏览器方式以 CRLF 发送。
                tags=[box.replace("\n", "\r\n") for box in reprinted_boxes],
            ),
        )
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(
            headers["Location"], f"/?highlight={self.track_id}&edited=1"
        )

        record = self.track_by_id(self.track_id)
        # 保存的是失败前用户填写的标签（末尾空框按空项忽略），
        # 没有回到旧标签，顺序也不变。
        self.assertEqual(record["tags"], edited_tags_lf)
        self.assertEqual(record["duration"], 240)

        # 再次打开编辑页，页面内容与保存结果一致。
        reopened = self.get_edit_page(self.track_id)
        self.assert_tag_boxes(reopened, edited_tags_lf + [""])
        self.assert_form_values(reopened, duration="240")


class EditPageTagNewlinePreservationTest(ServerTestCase):
    """标签原文含 CRLF/CR 换行：未修改的项保存后逐字节不变、不被合并。

    准备数据的四项标签覆盖：仅换行写法不同（CRLF 与 LF）的两项“自然/雨声”、
    含单独 CR 换行的一项、含标点的一项。接口收录时按完整文字保存，编辑页
    未修改的框在保存后必须保留各自原文。
    """

    CRLF_TAG = "自然\r\n雨声"
    LF_TAG = "自然\n雨声"
    CR_TAG = "风声\r落叶"
    PUNCT_TAG = "晨间，鸟鸣、溪流"
    INITIAL_TAGS = [CRLF_TAG, LF_TAG, CR_TAG, PUNCT_TAG]

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="山涧晨曲",
            source="/music/shanjian.flac",
            duration=212,
            description="清晨山涧录音",
            tags=self.INITIAL_TAGS,
        )
        self.track_id = self.track["id"]

    def fetch_tag_pairs(self, track_id=None):
        """从真实编辑页取回 [(框内文字, 原始序号), ...]，模拟浏览器打开页面。"""
        page = self.get_edit_page(track_id or self.track_id)
        boxes = parse_tag_boxes(page)
        refs = parse_tag_refs(page)
        self.assertEqual(
            len(refs), len(boxes),
            f"每个标签框都应配一个原始序号隐藏域：{refs!r} vs {boxes!r}",
        )
        return list(zip(boxes, refs))

    def submit_tag_pairs(self, pairs, track_id=None, **fields):
        """模拟浏览器整表提交：框内换行按 CRLF 编码，序号隐藏域随框提交。"""
        form = self.edit_form_fields(
            title=fields.pop("title", "山涧晨曲"),
            source=fields.pop("source", "/music/shanjian.flac"),
            duration=fields.pop("duration", "212"),
            description=fields.pop("description", "清晨山涧录音"),
            tags=[browser_newlines(text) for text, _ in pairs],
            **fields,
        )
        form.extend(("tags_ref", ref) for _, ref in pairs)
        return self.post_edit_form(track_id or self.track_id, form)

    def test_edit_page_marks_each_box_with_its_original_index(self):
        pairs = self.fetch_tag_pairs()
        # 四个已有框依次对应原始序号 0..3，末尾新增框没有序号。
        self.assertEqual(
            pairs,
            [(self.CRLF_TAG, "0"), (self.LF_TAG, "1"),
             (self.CR_TAG, "2"), (self.PUNCT_TAG, "3"), ("", "")],
        )

    def test_save_without_touching_tags_preserves_original_bytes(self):
        # 直接保存（只改名称）：四项原文逐字节保留，CRLF/LF 两项不被合并。
        status, headers, page = self.submit_tag_pairs(
            self.fetch_tag_pairs(), title="山涧晨曲（定稿）",
        )
        self.assertEqual(status, 303, page[:500])

        record = self.track_by_id(self.track_id)
        self.assertEqual(record["title"], "山涧晨曲（定稿）")
        self.assertEqual(record["tags"], self.INITIAL_TAGS)
        self.assertIn("\r\n", record["tags"][0])
        self.assertNotIn("\r", record["tags"][1])
        self.assertIn("\r", record["tags"][2])
        self.assertNotIn("\r\n", record["tags"][2])

    def test_repeated_untouched_saves_keep_tags_stable(self):
        for round_index in range(2):
            status, _, page = self.submit_tag_pairs(
                self.fetch_tag_pairs(), title=f"改名第 {round_index} 次",
            )
            self.assertEqual(status, 303, page[:500])
            self.assertEqual(
                self.track_by_id(self.track_id)["tags"], self.INITIAL_TAGS
            )

    def test_deleting_one_newline_variant_keeps_the_others_raw_text(self):
        # 两项画面相同、仅换行写法不同：删掉 CRLF 项，LF 项保留自己的原文。
        pairs = self.fetch_tag_pairs()
        del pairs[0]
        status, _, page = self.submit_tag_pairs(pairs)
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(
            self.track_by_id(self.track_id)["tags"],
            [self.LF_TAG, self.CR_TAG, self.PUNCT_TAG],
        )

    def test_deleting_lf_variant_keeps_crlf_variant_raw_text(self):
        # 反向对照：删掉 LF 项，CRLF 项的换行写法不被改写。
        pairs = self.fetch_tag_pairs()
        del pairs[1]
        status, _, page = self.submit_tag_pairs(pairs)
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(
            self.track_by_id(self.track_id)["tags"],
            [self.CRLF_TAG, self.CR_TAG, self.PUNCT_TAG],
        )

    def test_surrounding_whitespace_only_still_counts_as_untouched(self):
        # 只给整项首尾增加空白：保留原项内部的换行写法。
        pairs = self.fetch_tag_pairs()
        pairs[0] = ("  " + pairs[0][0] + "\t ", pairs[0][1])
        status, _, page = self.submit_tag_pairs(pairs)
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(
            self.track_by_id(self.track_id)["tags"], self.INITIAL_TAGS
        )

    def test_modifying_one_item_saves_lf_for_it_and_keeps_other_raw_texts(self):
        # 确实修改第二项的文字：该项按本次填写（LF）保存，其余项原文不变。
        pairs = self.fetch_tag_pairs()
        pairs[1] = ("雨声\r\n新版本", pairs[1][1])
        status, _, page = self.submit_tag_pairs(pairs)
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(
            self.track_by_id(self.track_id)["tags"],
            [self.CRLF_TAG, "雨声\n新版本", self.CR_TAG, self.PUNCT_TAG],
        )

    def test_new_item_deduplicates_against_final_full_text_only(self):
        # 新增一项与 LF 项最终文字完全相同：按首次出现去重；
        # 但 CRLF 项不因画面相同被合并。
        pairs = self.fetch_tag_pairs()
        pairs.append(("自然\n雨声", ""))
        status, _, page = self.submit_tag_pairs(pairs)
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(
            self.track_by_id(self.track_id)["tags"], self.INITIAL_TAGS
        )

    def test_modified_item_matching_another_final_text_is_deduplicated(self):
        # 把 CR 项改成与 LF 项完全相同的文字：修改后的标签正常参与去重。
        pairs = self.fetch_tag_pairs()
        pairs[2] = ("自然\n雨声", pairs[2][1])
        status, _, page = self.submit_tag_pairs(pairs)
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(
            self.track_by_id(self.track_id)["tags"],
            [self.CRLF_TAG, self.LF_TAG, self.PUNCT_TAG],
        )

    def test_failed_save_reprint_keeps_refs_and_retry_preserves_originals(self):
        # 时长不合法导致保存失败：记录不变，回填页面仍带各项原始序号。
        status, _, page = self.submit_tag_pairs(
            self.fetch_tag_pairs(), duration="-5",
        )
        self.assertEqual(status, 400)
        self.assertEqual(self.track_by_id(self.track_id), self.track)
        boxes = parse_tag_boxes(page)
        refs = parse_tag_refs(page)
        # 提交时的末尾空框也逐框回填，页面再附一个空框。
        self.assertEqual(refs, ["0", "1", "2", "3", "", ""])
        # 回填框内文字按 LF 呈现（浏览器提交写法的归一化结果）。
        self.assertEqual(
            boxes,
            ["自然\n雨声", "自然\n雨声", "风声\n落叶", self.PUNCT_TAG, "", ""],
        )

        # 只修正时长后再次保存：未修改的各项仍还原原始完整文字，
        # 不因经过错误页面丢掉一项或把 CRLF/CR 改写成 LF。
        retry_pairs = list(zip(boxes, refs))
        status, headers, page = self.submit_tag_pairs(
            retry_pairs, duration="240",
        )
        self.assertEqual(status, 303, page[:500])
        record = self.track_by_id(self.track_id)
        self.assertEqual(record["duration"], 240)
        self.assertEqual(record["tags"], self.INITIAL_TAGS)

    def test_source_conflict_reprint_and_retry_preserves_originals(self):
        # 来源冲突导致保存失败：同样回填序号，修正后来源与标签都正确保存。
        self.create_track(title="占位", source="/music/taken.flac")
        status, _, page = self.submit_tag_pairs(
            self.fetch_tag_pairs(), source="/music/taken.flac",
        )
        self.assertEqual(status, 409)
        self.assertEqual(self.track_by_id(self.track_id), self.track)

        boxes = parse_tag_boxes(page)
        refs = parse_tag_refs(page)
        status, _, page = self.submit_tag_pairs(
            list(zip(boxes, refs)), source="/music/shanjian-2.flac",
        )
        self.assertEqual(status, 303, page[:500])
        record = self.track_by_id(self.track_id)
        self.assertEqual(record["source"], "/music/shanjian-2.flac")
        self.assertEqual(record["tags"], self.INITIAL_TAGS)


class EditPageDescriptionRenderTest(ServerTestCase):
    """打开编辑页：说明框完整还原原说明的空行、换行与首尾空格。"""

    MULTIBLANK_DESCRIPTION = "\n\n第一段说明\n\n第二段说明\n"

    def test_leading_paragraph_and_trailing_blank_lines_render_in_box(self):
        track = self.create_track(
            title="空行说明曲目",
            source="/music/blanks.flac",
            description=self.MULTIBLANK_DESCRIPTION,
        )
        page = self.get_edit_page(track["id"])
        shown = parse_description_box(page)
        # 开头两个空行、段落之间的空行、结尾空行都出现在相同位置。
        self.assertEqual(shown, self.MULTIBLANK_DESCRIPTION)
        self.assertEqual(
            shown.split("\n"),
            ["", "", "第一段说明", "", "第二段说明", ""],
        )
        # 服务端在标记里补写了一个开头换行，抵消 HTML 解析吞掉首换行的
        # 规则（原文两个开头换行，标记里共三个，解析后剩两个）。
        self.assertIn(
            'name="description">\n\n\n第一段说明',
            description_box_markup(page),
        )

    def test_normal_description_gains_no_extra_blank_line(self):
        track = self.create_track(
            title="普通说明曲目",
            source="/music/plain.flac",
            description="普通说明\n第二行",
        )
        page = self.get_edit_page(track["id"])
        self.assertEqual(parse_description_box(page), "普通说明\n第二行")
        # 没有开头空行时不能凭空补一行：正文紧跟在起始标签之后。
        self.assertIn(
            'name="description">普通说明',
            description_box_markup(page),
        )

    def test_empty_description_box_is_truly_empty(self):
        track = self.create_track(
            title="空说明曲目", source="/music/empty.flac", description=""
        )
        page = self.get_edit_page(track["id"])
        self.assertEqual(parse_description_box(page), "")
        self.assertIn(
            '<textarea id="f-description" name="description"></textarea>',
            page,
        )

    def test_whitespace_only_descriptions_render_distinctly(self):
        cases = {
            "spaces": "   ",
            "blank-lines": "\n\n",
            "mixed": "  \n \t\n ",
        }
        for name, description in cases.items():
            with self.subTest(case=name):
                track = self.create_track(
                    title=name,
                    source=f"/music/{name}.flac",
                    description=description,
                )
                page = self.get_edit_page(track["id"])
                self.assertEqual(
                    parse_description_box(page), description, name
                )

    def test_leading_and_trailing_spaces_are_preserved(self):
        description = "\n  缩进开头的第一段（两侧留空格）  \n\t制表符结尾\n"
        track = self.create_track(
            title="首尾空格曲目",
            source="/music/spaces.flac",
            description=description,
        )
        page = self.get_edit_page(track["id"])
        self.assertEqual(parse_description_box(page), description)

    def test_crlf_description_renders_with_same_blank_lines(self):
        description_crlf = self.MULTIBLANK_DESCRIPTION.replace("\n", "\r\n")
        track = self.create_track(
            title="CRLF 说明曲目",
            source="/music/crlf.flac",
            description=description_crlf,
        )
        page = self.get_edit_page(track["id"])
        # 浏览器把框内 CRLF 呈现为同样的换行与空行位置。
        self.assertEqual(
            parse_description_box(page), self.MULTIBLANK_DESCRIPTION
        )

    def test_html_looking_text_is_displayed_as_plain_text(self):
        description = (
            '中文“引号”与英文"引号"\n'
            "<尖括号> 与 <img src=x onerror=alert(1)> 看起来像标签\n"
            "</textarea><script>alert(1)</script>  结尾两空格"
        )
        track = self.create_track(
            title="特殊字符曲目",
            source="/music/special.flac",
            description=description,
        )
        page = self.get_edit_page(track["id"])
        # 文字原样回到框内，包括结尾两个空格。
        self.assertEqual(parse_description_box(page), description)
        markup = description_box_markup(page)
        # 尖括号、引号都被转义，说明文字不会变成页面元素。
        self.assertNotIn("<script>", markup)
        self.assertNotIn("<img ", markup)
        self.assertNotIn("</textarea><", markup)
        self.assertIn("&lt;script&gt;", markup)
        self.assertIn("&lt;/textarea&gt;", markup)
        self.assertIn("&quot;引号&quot;", markup)
        self.assertNotIn('<script>alert(1)</script>', page)


class EditPageDescriptionUntouchedSaveTest(ServerTestCase):
    """不碰说明框、只改名称等其他资料：保存后说明必须逐字节不变。"""

    MULTIBLANK_LF = "\n\n第一段说明\n\n第二段说明\n"

    def save_untouched_form(self, track, *, description_submitted):
        """模拟浏览器整表提交：改名称、改封面，说明按给定文字原样提交。"""
        fields = self.edit_form_fields(
            title="新名称",
            source="/music/desc.flac",
            duration="212",
            cover_url="https://img.example/new.png",
            description=description_submitted,
            tags=["原标签"],
        )
        status, headers, page = self.post_edit_form(track["id"], fields)
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(
            headers["Location"], f"/?highlight={track['id']}&edited=1"
        )
        return self.track_by_id(track["id"])

    def test_lf_description_survives_browser_crlf_submission(self):
        track = self.create_track(
            title="原名",
            source="/music/desc.flac",
            duration=212,
            cover_url="https://img.example/old.png",
            description=self.MULTIBLANK_LF,
            tags=["原标签"],
        )
        # 浏览器把框内换行按 CRLF 提交。
        record = self.save_untouched_form(
            track,
            description_submitted=self.MULTIBLANK_LF.replace("\n", "\r\n"),
        )
        self.assertEqual(record["title"], "新名称")
        self.assertEqual(record["cover_url"], "https://img.example/new.png")
        # 说明与保存前逐字节相同：仍是 LF，开头/段落/结尾空行都在。
        self.assertEqual(record["description"], self.MULTIBLANK_LF)
        self.assertNotIn("\r", record["description"])
        self.assertEqual(record["tags"], ["原标签"])
        self.assertEqual(record["id"], track["id"])

    def test_crlf_description_survives_crlf_submission(self):
        description_crlf = self.MULTIBLANK_LF.replace("\n", "\r\n")
        track = self.create_track(
            title="原名",
            source="/music/desc.flac",
            duration=212,
            description=description_crlf,
        )
        record = self.save_untouched_form(
            track, description_submitted=description_crlf
        )
        # 原说明的 CRLF 写法逐字节保留，没有被改成 LF。
        self.assertEqual(record["description"], description_crlf)

    def test_raw_lf_submission_also_keeps_original(self):
        track = self.create_track(
            title="原名",
            source="/music/desc.flac",
            duration=212,
            description=self.MULTIBLANK_LF,
        )
        # 非浏览器客户端直接按 LF 提交同样的文字：仍是“未改动”，原样保留。
        record = self.save_untouched_form(
            track, description_submitted=self.MULTIBLANK_LF
        )
        self.assertEqual(record["description"], self.MULTIBLANK_LF)

    def test_roundtrip_through_rendered_page_keeps_original_bytes(self):
        for name, original in (
            ("lf", self.MULTIBLANK_LF),
            ("crlf", self.MULTIBLANK_LF.replace("\n", "\r\n")),
        ):
            with self.subTest(case=name):
                track = self.create_track(
                    title=f"原名-{name}",
                    source=f"/music/{name}.flac",
                    duration=212,
                    description=original,
                )
                # 从真实编辑页取框内文字，再按浏览器方式（CRLF）提交。
                page = self.get_edit_page(track["id"])
                shown = parse_description_box(page)
                fields = self.edit_form_fields(
                    title=f"新名称-{name}",
                    source=f"/music/{name}.flac",
                    duration="212",
                    description=shown.replace("\n", "\r\n"),
                )
                status, _, resp = self.post_edit_form(track["id"], fields)
                self.assertEqual(status, 303, resp[:500])
                self.assertEqual(
                    self.track_by_id(track["id"])["description"], original
                )

    def test_empty_blank_and_spaces_descriptions_are_not_swapped(self):
        # 看起来都“没有正文”，但空串、纯空行、纯空格必须各自保留。
        variants = ["", "\n", "\n\n", " ", "   ", " \n \t"]
        for index, original in enumerate(variants):
            with self.subTest(original=repr(original)):
                track = self.create_track(
                    title=f"变体 {index}",
                    source=f"/music/variant-{index}.flac",
                    description=original,
                )
                page = self.get_edit_page(track["id"])
                shown = parse_description_box(page)
                fields = self.edit_form_fields(
                    title=f"变体 {index} 改名",
                    source=f"/music/variant-{index}.flac",
                    description=shown.replace("\n", "\r\n"),
                )
                status, _, resp = self.post_edit_form(track["id"], fields)
                self.assertEqual(status, 303, resp[:500])
                self.assertEqual(
                    self.track_by_id(track["id"])["description"], original
                )

    def test_repeated_saves_keep_description_stable(self):
        track = self.create_track(
            title="原名",
            source="/music/desc.flac",
            duration=212,
            description=self.MULTIBLANK_LF,
        )
        for round_index in range(2):
            page = self.get_edit_page(track["id"])
            shown = parse_description_box(page)
            fields = self.edit_form_fields(
                title=f"改名第 {round_index} 次",
                source="/music/desc.flac",
                duration="212",
                description=shown.replace("\n", "\r\n"),
            )
            status, _, resp = self.post_edit_form(track["id"], fields)
            self.assertEqual(status, 303, resp[:500])
            self.assertEqual(
                self.track_by_id(track["id"])["description"],
                self.MULTIBLANK_LF,
            )


class EditPageDescriptionChangesTest(ServerTestCase):
    """确实编辑说明时按本次填写保存，未改动保护不禁止修改。"""

    def test_edited_description_is_saved_with_lf_newlines(self):
        track = self.create_track(
            title="说明可改曲目",
            source="/music/edit-desc.flac",
            duration=100,
            description="旧说明\n第二行",
            tags=["旧标签"],
        )
        new_description = "\n\n新的开头空行\n\n新第二段\n"
        fields = self.edit_form_fields(
            title="说明可改曲目",
            source="/music/edit-desc.flac",
            duration="100",
            description=new_description.replace("\n", "\r\n"),
            tags=["旧标签"],
        )
        status, headers, page = self.post_edit_form(track["id"], fields)
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(
            headers["Location"], f"/?highlight={track['id']}&edited=1"
        )
        record = self.track_by_id(track["id"])
        # 保存的是本次填写的文字与空行安排（换行统一为 LF），不是旧说明。
        self.assertEqual(record["description"], new_description)
        self.assertEqual(record["tags"], ["旧标签"])

        # 再次打开编辑页，框内就是新说明。
        page = self.get_edit_page(track["id"])
        self.assertEqual(parse_description_box(page), new_description)

    def test_clearing_description_saves_empty_string(self):
        track = self.create_track(
            title="删空说明曲目",
            source="/music/clear.flac",
            description="原本有说明",
        )
        fields = self.edit_form_fields(
            title="删空说明曲目",
            source="/music/clear.flac",
            description="",
        )
        status, _, page = self.post_edit_form(track["id"], fields)
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(
            self.track_by_id(track["id"])["description"], ""
        )

    def test_changing_text_to_whitespace_only_saves_whitespace(self):
        track = self.create_track(
            title="改成空白曲目",
            source="/music/whitespace.flac",
            description="有正文的说明",
        )
        fields = self.edit_form_fields(
            title="改成空白曲目",
            source="/music/whitespace.flac",
            description="  \n ".replace("\n", "\r\n"),
        )
        status, _, page = self.post_edit_form(track["id"], fields)
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(
            self.track_by_id(track["id"])["description"], "  \n "
        )

    def test_changing_empty_description_to_text_saves_text(self):
        track = self.create_track(
            title="补写说明曲目",
            source="/music/fill.flac",
            description="",
        )
        fields = self.edit_form_fields(
            title="补写说明曲目",
            source="/music/fill.flac",
            description="新补写的说明",
        )
        status, _, page = self.post_edit_form(track["id"], fields)
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(
            self.track_by_id(track["id"])["description"], "新补写的说明"
        )


class EditPageDescriptionSaveFailureTest(ServerTestCase):
    """其他字段非法导致保存失败：记录不变，说明按本次填写回填，修正后可保存。"""

    def test_failure_reprints_submitted_description_with_leading_blanks(self):
        original = "\n\n原始第一段\n\n原始第二段\n"
        track = self.create_track(
            title="失败重试曲目",
            source="/music/retry.flac",
            duration=212,
            description=original,
        )
        # 用户改了说明（开头三个空行），同时把时长误填成负数。
        edited = "\n\n\n本次填写的说明\n开头三个空行\n结尾空行\n"
        fields = self.edit_form_fields(
            title="失败重试曲目",
            source="/music/retry.flac",
            duration="-5",
            description=edited.replace("\n", "\r\n"),
        )
        status, _, page = self.post_edit_form(track["id"], fields)
        self.assertEqual(status, 400)
        banner = BANNER_ERROR_RE.search(page)
        self.assertIsNotNone(banner)
        self.assertIn("时长", strip_tags(banner.group(1)))

        # 原曲目保持原样：说明仍是旧原文。
        self.assertEqual(
            self.track_by_id(track["id"])["description"], original
        )
        # 重绘页面回填本次填写的说明，开头三个空行一行不少，
        # 既不是旧说明，也不是少了一行的版本。
        self.assertEqual(parse_description_box(page), edited)
        self.assert_form_values(page, duration="-5")

        # 只把时长修正为正数后继续保存：保存回填的说明内容。
        reprinted = parse_description_box(page)
        fields = self.edit_form_fields(
            title="失败重试曲目",
            source="/music/retry.flac",
            duration="240",
            description=reprinted.replace("\n", "\r\n"),
        )
        status, headers, resp = self.post_edit_form(track["id"], fields)
        self.assertEqual(status, 303, resp[:500])
        self.assertEqual(
            headers["Location"], f"/?highlight={track['id']}&edited=1"
        )
        record = self.track_by_id(track["id"])
        self.assertEqual(record["description"], edited)
        self.assertEqual(record["duration"], 240)

    def test_failure_with_untouched_description_reprints_original_blanks(self):
        original = "\n\n原始第一段\n\n原始第二段\n"
        track = self.create_track(
            title="未动说明曲目",
            source="/music/untouched.flac",
            duration=212,
            description=original,
        )
        # 用户没碰说明框（框内文字按 CRLF 提交），只把时长填成负数。
        fields = self.edit_form_fields(
            title="未动说明曲目",
            source="/music/untouched.flac",
            duration="-5",
            description=original.replace("\n", "\r\n"),
        )
        status, _, page = self.post_edit_form(track["id"], fields)
        self.assertEqual(status, 400)
        # 记录完全不变；重绘的说明仍是原说明，开头空行不丢。
        self.assertEqual(
            self.track_by_id(track["id"])["description"], original
        )
        self.assertEqual(parse_description_box(page), original)

        # 修正时长后保存：说明未改动，仍为原说明。
        fields = self.edit_form_fields(
            title="未动说明曲目",
            source="/music/untouched.flac",
            duration="240",
            description=original.replace("\n", "\r\n"),
        )
        status, headers, resp = self.post_edit_form(track["id"], fields)
        self.assertEqual(status, 303, resp[:500])
        record = self.track_by_id(track["id"])
        self.assertEqual(record["description"], original)
        self.assertEqual(record["duration"], 240)


class EditPageSourceRenderTest(ServerTestCase):
    """打开编辑页：来源框完整还原已保存来源的内部文字、空格与分行。"""

    MULTILINE_SOURCE = (
        "现场录音/第一段\n第二段：分轨 01.flac\n  缩进的第三行  \n\n空行之后的段落"
    )

    def test_multiline_source_renders_line_by_line_in_source_box(self):
        track = self.create_track(title="多行来源", source=self.MULTILINE_SOURCE)
        page = self.get_edit_page(track["id"])
        # 框内文字与已保存来源一致：内部换行、行内与行尾空格、空行都在。
        self.assertEqual(parse_source_box(page), self.MULTILINE_SOURCE)

    def test_crlf_and_cr_sources_render_with_same_lines(self):
        for raw in ("第一段\r\n第二段\r\n第三段", "第一段\r第二段"):
            with self.subTest(raw=raw):
                track = self.create_track(title="换行写法", source=raw)
                page = self.get_edit_page(track["id"])
                # 浏览器把 CRLF/CR 都显示为换行：框内呈现相同的行与文字。
                self.assertEqual(
                    parse_source_box(page),
                    raw.replace("\r\n", "\n").replace("\r", "\n"),
                )

    def test_html_looking_source_is_shown_as_plain_text(self):
        source = '/music/<b>not-bold</b>&"quotes"\n第二行<script>'
        track = self.create_track(title="转义来源", source=source)
        page = self.get_edit_page(track["id"])
        self.assertEqual(parse_source_box(page), source)
        # 标记内部按普通文字转义，不会被当成网页标签。
        match = SOURCE_RE.search(page)
        self.assertIn("&lt;b&gt;", match.group(0))
        self.assertNotIn("<b>not-bold</b>", match.group(0))


class EditPageSourceUntouchedSaveTest(ServerTestCase):
    """未改来源（或仅增删首尾空白）的保存：原来源完整文字逐字节保留。"""

    LF_SOURCE = "现场录音/第一段\n第二段：分轨 01.flac\n  缩进行  \n\n结尾段"
    CRLF_SOURCE = LF_SOURCE.replace("\n", "\r\n")
    CR_SOURCE = "第一段\r第二段\r第三段"

    def save_via_form(self, track, **changes):
        """模拟浏览器：打开编辑页，整表取回（textarea 换行按 CRLF 提交）。"""
        page = self.get_edit_page(track["id"])
        fields = self.edit_fields_from_rendered_page(page)
        fields = [
            (name, browser_newlines(value))
            if name in ("source", "description", "tags") else (name, value)
            for name, value in fields
        ]
        for name, value in changes.items():
            fields = self.form_with_field(fields, name, value)
        return self.post_edit_form(track["id"], fields)

    def assert_source_preserved(self, source):
        track = self.create_track(title="多行来源曲目", source=source)
        status, _, page = self.save_via_form(track, title="只改了名称")
        self.assertEqual(status, 303, page[:500])
        record = self.track_by_id(track["id"])
        self.assertEqual(record["title"], "只改了名称")
        # 原来源逐字节保留：换行写法不因网页显示与表单提交被改写。
        self.assertEqual(record["source"], source)
        return record

    def test_lf_source_survives_browser_crlf_submission(self):
        record = self.assert_source_preserved(self.LF_SOURCE)
        self.assertNotIn("\r", record["source"])

    def test_crlf_source_survives_browser_crlf_submission(self):
        record = self.assert_source_preserved(self.CRLF_SOURCE)
        self.assertIn("\r\n", record["source"])

    def test_cr_source_survives_browser_crlf_submission(self):
        record = self.assert_source_preserved(self.CR_SOURCE)
        self.assertIn("\r", record["source"])
        self.assertNotIn("\r\n", record["source"])

    def test_repeated_resaves_keep_source_stable(self):
        track = self.create_track(title="反复保存", source=self.CRLF_SOURCE)
        for round_index in range(2):
            status, _, page = self.save_via_form(
                self.track_by_id(track["id"]), title=f"第 {round_index} 次改名",
            )
            self.assertEqual(status, 303, page[:500])
            self.assertEqual(
                self.track_by_id(track["id"])["source"], self.CRLF_SOURCE
            )

    def test_surrounding_whitespace_only_counts_as_untouched(self):
        track = self.create_track(title="首尾空白", source=self.CRLF_SOURCE)
        page = self.get_edit_page(track["id"])
        fields = self.edit_fields_from_rendered_page(page)
        # 用户只在来源首尾增删空白（含换行），内部一字未动。
        padded = "  \r\n" + browser_newlines(self.LF_SOURCE) + "\t \r\n"
        fields = self.form_with_field(fields, "source", padded)
        status, _, page = self.post_edit_form(track["id"], fields)
        self.assertEqual(status, 303, page[:500])
        # 仍保留原来源的完整文字，不按去掉首尾空白后的文字重写。
        self.assertEqual(
            self.track_by_id(track["id"])["source"], self.CRLF_SOURCE
        )

    def test_newline_style_variants_stay_two_distinct_sources(self):
        # 两段来源只在内部换行写法上不同：各自保留，打开编辑页再保存
        # 不会把它们变成同一个来源。
        lf_track = self.create_track(title="LF 版本", source="甲\n乙")
        crlf_track = self.create_track(title="CRLF 版本", source="甲\r\n乙")

        status, _, page = self.save_via_form(lf_track, title="LF 版本（改名）")
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(self.track_by_id(lf_track["id"])["source"], "甲\n乙")
        self.assertEqual(
            self.track_by_id(crlf_track["id"])["source"], "甲\r\n乙"
        )

        status, _, page = self.save_via_form(crlf_track, title="CRLF 版本（改名）")
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(self.track_by_id(lf_track["id"])["source"], "甲\n乙")
        self.assertEqual(
            self.track_by_id(crlf_track["id"])["source"], "甲\r\n乙"
        )

    def test_newline_stripped_collision_does_not_block_untouched_save(self):
        # 另一曲目的来源恰好等于本来源去掉换行后的文字：不影响未改来源的保存。
        multiline = self.create_track(title="多行来源", source="甲\n乙")
        flat = self.create_track(title="单行来源", source="甲乙")

        status, _, page = self.save_via_form(multiline, title="多行来源（改名）")
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(self.track_by_id(multiline["id"])["source"], "甲\n乙")
        self.assertEqual(self.track_by_id(flat["id"])["source"], "甲乙")

    def test_same_multiline_source_versions_edit_via_form_succeeds(self):
        # 其他版本共用同一多行来源时，网页编辑其中一条的其他资料仍应成功。
        shared = "共用来源/第一段\n第二段.flac"
        first = self.create_track(title="版本一", source=shared, duration=100)
        second = self.create_track(
            title="版本二", source=shared, duration=200,
            save_as_new_version=True,
        )
        status, _, page = self.save_via_form(second, title="版本二（改名）")
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(self.track_by_id(second["id"])["source"], shared)
        self.assertEqual(self.track_by_id(first["id"]), first)
        self.assertEqual(len(self.list_tracks()), 2)


class EditPageSourceChangesTest(ServerTestCase):
    """确实修改来源内部文字、空格或分行：按本次填写（LF）去掉首尾空白保存。"""

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="待改来源", source="/music/old.flac", duration=120,
            description="原始说明",
        )
        self.track_id = self.track["id"]

    def submit_source(self, source_text, **changes):
        page = self.get_edit_page(self.track_id)
        fields = self.edit_fields_from_rendered_page(page)
        fields = self.form_with_field(fields, "source", source_text)
        for name, value in changes.items():
            fields = self.form_with_field(fields, name, value)
        return self.post_edit_form(self.track_id, fields)

    def test_edited_source_saved_with_lf_newlines_and_trimmed(self):
        typed = "  新的来源/第一段\r\n第二段  \r\n\r\n第三段\r\n "
        status, headers, page = self.submit_source(typed)
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(
            headers["Location"], f"/?highlight={self.track_id}&edited=1"
        )
        # 内部换行统一为 LF，首尾空白去掉，内部文字与空行保留。
        saved = "新的来源/第一段\n第二段  \n\n第三段"
        record = self.track_by_id(self.track_id)
        self.assertEqual(record["source"], saved)
        # 接口随后读到的来源与保存结果一致，标识不变、不新增记录。
        self.assertEqual(record["id"], self.track_id)
        self.assertEqual(len(self.list_tracks()), 1)
        # 重新打开编辑页，来源框呈现保存后的完整文字。
        self.assertEqual(parse_source_box(self.get_edit_page(self.track_id)), saved)

    def test_internal_space_or_case_difference_is_not_a_conflict(self):
        self.create_track(title="占用者", source="ab.flac")
        status, _, page = self.submit_source("AB.flac")
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(self.track_by_id(self.track_id)["source"], "AB.flac")

        self.create_track(title="空格占用者", source="a b.flac")
        status, _, page = self.submit_source("a  b.flac")
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(self.track_by_id(self.track_id)["source"], "a  b.flac")

    def test_changed_source_matching_other_track_is_rejected(self):
        occupant = self.create_track(title="实际占用者", source="乙\n丙")
        # 网页按 CRLF 提交的新来源归一化后与占用者完整文字相同：拒绝。
        status, _, page = self.submit_source("乙\r\n丙")
        self.assertEqual(status, 409, page[:500])
        self.assertEqual(
            parse_conflict_items(page), [(occupant["id"], "实际占用者")]
        )
        # 整条曲目保持原样，页面保留本次填写的来源与其他资料。
        self.assertEqual(self.track_by_id(self.track_id), self.track)
        self.assertEqual(parse_source_box(page), "乙\n丙")
        self.assert_form_values(page, title="待改来源", duration="120")

        # 用户改成未占用的来源后继续保存：采用回填内容，标识不变。
        status, headers, page = self.submit_source("/music/free.flac")
        self.assertEqual(status, 303, page[:500])
        record = self.track_by_id(self.track_id)
        self.assertEqual(record["source"], "/music/free.flac")
        self.assertEqual(record["id"], self.track_id)
        self.assertEqual(len(self.list_tracks()), 2)

    def test_clearing_existing_source_is_rejected(self):
        for blank in ("", "   \r\n  "):
            with self.subTest(blank=repr(blank)):
                status, _, page = self.submit_source(blank)
                self.assertEqual(status, 400, page[:500])
                banner = BANNER_ERROR_RE.search(page)
                self.assertIsNotNone(banner)
                self.assertIn("来源", strip_tags(banner.group(1)))
                # 已有来源不能被清空：整条记录保持原样。
                self.assertEqual(self.track_by_id(self.track_id), self.track)


class EditPageSourceSaveFailureTest(ServerTestCase):
    """时长等错误导致保存失败：记录不变，来源按本次填写回填，修正后续存。"""

    CRLF_SOURCE = "第一段\r\n第二段\r\n第三段"

    def test_untouched_source_survives_failure_reprint_and_retry(self):
        track = self.create_track(
            title="失败重试", source=self.CRLF_SOURCE, duration=120,
        )
        # 用户没碰来源框（框内文字按 CRLF 提交），只把时长填成负数。
        page = self.get_edit_page(track["id"])
        fields = self.edit_fields_from_rendered_page(page)
        fields = self.form_with_field(fields, "duration", "-5")
        fields = [
            (name, browser_newlines(value))
            if name in ("source", "description", "tags") else (name, value)
            for name, value in fields
        ]
        status, _, page = self.post_edit_form(track["id"], fields)
        self.assertEqual(status, 400)
        # 整条记录保持原样；来源框回填本次提交的文字（LF 呈现）。
        self.assertEqual(self.track_by_id(track["id"]), track)
        self.assertEqual(
            parse_source_box(page), self.CRLF_SOURCE.replace("\r\n", "\n")
        )
        self.assert_form_values(page, duration="-5")

        # 只修正时长后继续保存：未改来源仍保留原 CRLF 原文。
        fields = self.edit_fields_from_rendered_page(page)
        fields = self.form_with_field(fields, "duration", "240")
        fields = [
            (name, browser_newlines(value))
            if name in ("source", "description", "tags") else (name, value)
            for name, value in fields
        ]
        status, _, page = self.post_edit_form(track["id"], fields)
        self.assertEqual(status, 303, page[:500])
        record = self.track_by_id(track["id"])
        self.assertEqual(record["source"], self.CRLF_SOURCE)
        self.assertEqual(record["duration"], 240)

    def test_modified_source_in_failed_save_is_reprinted_and_saved_on_retry(self):
        track = self.create_track(
            title="失败重试", source="/music/old.flac", duration=120,
        )
        typed = "改过的来源/第一段\r\n第二段"
        page = self.get_edit_page(track["id"])
        fields = self.edit_fields_from_rendered_page(page)
        fields = self.form_with_field(fields, "source", typed)
        fields = self.form_with_field(fields, "duration", "-5")
        status, _, page = self.post_edit_form(track["id"], fields)
        self.assertEqual(status, 400)
        self.assertEqual(self.track_by_id(track["id"]), track)
        # 确实改过的来源按本次填写回填（LF 呈现），修正时长后保存回填内容。
        self.assertEqual(parse_source_box(page), "改过的来源/第一段\n第二段")

        fields = self.edit_fields_from_rendered_page(page)
        fields = self.form_with_field(fields, "duration", "240")
        fields = [
            (name, browser_newlines(value))
            if name in ("source", "description", "tags") else (name, value)
            for name, value in fields
        ]
        status, _, page = self.post_edit_form(track["id"], fields)
        self.assertEqual(status, 303, page[:500])
        record = self.track_by_id(track["id"])
        self.assertEqual(record["source"], "改过的来源/第一段\n第二段")
        self.assertEqual(record["duration"], 240)


class EditPageLegacySourceTest(ServerTestCase):
    """只有标识与名称、原本缺少来源的旧记录：网页编辑仍可留空或补填来源。"""

    def test_blank_source_stays_missing_when_resaved_via_form(self):
        legacy_id = self.server.insert_legacy("旧记录")
        page = self.get_edit_page(legacy_id)
        self.assertEqual(parse_source_box(page), "")
        fields = self.edit_fields_from_rendered_page(page)
        fields = self.form_with_field(fields, "title", "旧记录（改名）")
        status, _, page = self.post_edit_form(legacy_id, fields)
        self.assertEqual(status, 303, page[:500])
        record = self.track_by_id(legacy_id)
        self.assertIsNone(record["source"])
        self.assertEqual(record["title"], "旧记录（改名）")

    def test_filling_source_via_form_saves_it(self):
        legacy_id = self.server.insert_legacy("旧记录")
        page = self.get_edit_page(legacy_id)
        fields = self.edit_fields_from_rendered_page(page)
        fields = self.form_with_field(
            fields, "source", "补填的来源/第一段\r\n第二段"
        )
        status, _, page = self.post_edit_form(legacy_id, fields)
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(
            self.track_by_id(legacy_id)["source"], "补填的来源/第一段\n第二段"
        )

    def test_filling_occupied_source_via_form_is_rejected(self):
        occupant = self.create_track(title="占用者", source="/music/taken.flac")
        legacy_id = self.server.insert_legacy("旧记录")
        page = self.get_edit_page(legacy_id)
        fields = self.edit_fields_from_rendered_page(page)
        fields = self.form_with_field(fields, "source", "/music/taken.flac")
        status, _, page = self.post_edit_form(legacy_id, fields)
        self.assertEqual(status, 409, page[:500])
        self.assertEqual(
            parse_conflict_items(page), [(occupant["id"], "占用者")]
        )
        self.assertIsNone(self.track_by_id(legacy_id)["source"])


class EditPageCoverRenderTest(ServerTestCase):
    """打开编辑页：封面地址框完整还原已保存地址的内部文字、空格与分行。"""

    MULTILINE_COVER = (
        "https://img.example/封面 第一行.png\n第二行：分轨 01\n  缩进的第三行  "
        "\n\n空行之后的段落"
    )

    def test_multiline_cover_renders_line_by_line_in_cover_box(self):
        track = self.create_track(
            title="多行封面", source="/music/multi.flac",
            cover_url=self.MULTILINE_COVER,
        )
        page = self.get_edit_page(track["id"])
        # 框内文字与已保存地址一致：中文、内部换行、行内与行尾空格、空行都在。
        self.assertEqual(parse_cover_box(page), self.MULTILINE_COVER)

    def test_crlf_and_cr_covers_render_with_same_lines(self):
        for raw in ("第一行\r\n第二行\r\n第三行", "第一行\r第二行"):
            with self.subTest(raw=raw):
                track = self.create_track(
                    title="换行写法", source=f"/music/{len(raw)}.flac",
                    cover_url=raw,
                )
                page = self.get_edit_page(track["id"])
                # 浏览器把 CRLF/CR 都显示为换行：框内呈现相同的行与文字。
                self.assertEqual(
                    parse_cover_box(page),
                    raw.replace("\r\n", "\n").replace("\r", "\n"),
                )

    def test_html_looking_cover_is_shown_as_plain_text(self):
        cover = 'https://img.example/<b>not-bold</b>&"q"\n第二行<script>'
        track = self.create_track(
            title="转义封面", source="/music/special.flac", cover_url=cover,
        )
        page = self.get_edit_page(track["id"])
        self.assertEqual(parse_cover_box(page), cover)
        # 标记内部按普通文字转义，引号、尖括号与形似标签的文字不生成页面元素。
        match = COVER_RE.search(page)
        self.assertIn("&lt;b&gt;", match.group(0))
        self.assertNotIn("<b>not-bold</b>", match.group(0))
        self.assertNotIn("</textarea><", match.group(0))

    def test_empty_cover_renders_blank_box(self):
        track = self.create_track(
            title="无封面", source="/music/nocover.flac", cover_url="",
        )
        page = self.get_edit_page(track["id"])
        self.assertEqual(parse_cover_box(page), "")


class EditPageCoverUntouchedSaveTest(ServerTestCase):
    """未改封面地址（或仅增删首尾空白）的保存：原地址完整文字逐字节保留。"""

    LF_COVER = "https://img.example/第一段\n第二段  分轨\n  缩进行  \n\n结尾段"
    CRLF_COVER = LF_COVER.replace("\n", "\r\n")
    CR_COVER = "第一行\r第二行\r第三行"

    def save_via_form(self, track, **changes):
        """模拟浏览器：打开编辑页，整表取回（textarea 换行按 CRLF 提交）。"""
        page = self.get_edit_page(track["id"])
        fields = self.edit_fields_from_rendered_page(page)
        fields = [
            (name, browser_newlines(value))
            if name in ("source", "cover_url", "description", "tags")
            else (name, value)
            for name, value in fields
        ]
        for name, value in changes.items():
            fields = self.form_with_field(fields, name, value)
        return self.post_edit_form(track["id"], fields)

    def assert_cover_preserved(self, cover):
        track = self.create_track(
            title="多行封面曲目", source="/music/cover.flac", cover_url=cover,
        )
        status, _, page = self.save_via_form(track, title="只改了名称")
        self.assertEqual(status, 303, page[:500])
        record = self.track_by_id(track["id"])
        self.assertEqual(record["title"], "只改了名称")
        # 原地址逐字节保留：换行写法不因网页显示与表单提交被改写。
        self.assertEqual(record["cover_url"], cover)
        return record

    def test_lf_cover_survives_browser_crlf_submission(self):
        record = self.assert_cover_preserved(self.LF_COVER)
        self.assertNotIn("\r", record["cover_url"])

    def test_crlf_cover_survives_browser_crlf_submission(self):
        record = self.assert_cover_preserved(self.CRLF_COVER)
        self.assertIn("\r\n", record["cover_url"])

    def test_cr_cover_survives_browser_crlf_submission(self):
        record = self.assert_cover_preserved(self.CR_COVER)
        self.assertIn("\r", record["cover_url"])
        self.assertNotIn("\r\n", record["cover_url"])

    def test_changing_only_duration_keeps_cover_bytes(self):
        track = self.create_track(
            title="只调时长", source="/music/cover.flac",
            duration=212, cover_url=self.CRLF_COVER,
        )
        status, _, page = self.save_via_form(track, duration="300")
        self.assertEqual(status, 303, page[:500])
        record = self.track_by_id(track["id"])
        self.assertEqual(record["duration"], 300)
        self.assertEqual(record["cover_url"], self.CRLF_COVER)
        self.assertEqual(record["id"], track["id"])

    def test_repeated_resaves_keep_cover_stable(self):
        track = self.create_track(
            title="反复保存", source="/music/cover.flac", cover_url=self.CRLF_COVER,
        )
        for round_index in range(2):
            status, _, page = self.save_via_form(
                self.track_by_id(track["id"]), title=f"第 {round_index} 次改名",
            )
            self.assertEqual(status, 303, page[:500])
            self.assertEqual(
                self.track_by_id(track["id"])["cover_url"], self.CRLF_COVER
            )

    def test_surrounding_whitespace_only_counts_as_untouched(self):
        track = self.create_track(
            title="首尾空白", source="/music/cover.flac", cover_url=self.CRLF_COVER,
        )
        page = self.get_edit_page(track["id"])
        fields = self.edit_fields_from_rendered_page(page)
        # 用户只在地址首尾增删空白（含换行），内部一字未动。
        padded = "  \r\n" + browser_newlines(self.LF_COVER) + "\t \r\n"
        fields = self.form_with_field(fields, "cover_url", padded)
        status, _, page = self.post_edit_form(track["id"], fields)
        self.assertEqual(status, 303, page[:500])
        # 仍保留原地址的完整文字，不按去掉首尾空白后的文字重写。
        self.assertEqual(
            self.track_by_id(track["id"])["cover_url"], self.CRLF_COVER
        )

    def test_newline_style_variants_stay_two_distinct_covers(self):
        # 两段地址只在内部换行写法上不同：各自保留，打开编辑页再保存
        # 不会把它们变成同一个地址。
        lf_track = self.create_track(
            title="LF 版本", source="/music/lf.flac", cover_url="甲\n乙",
        )
        crlf_track = self.create_track(
            title="CRLF 版本", source="/music/crlf.flac", cover_url="甲\r\n乙",
        )

        status, _, page = self.save_via_form(lf_track, title="LF 版本（改名）")
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(self.track_by_id(lf_track["id"])["cover_url"], "甲\n乙")
        self.assertEqual(
            self.track_by_id(crlf_track["id"])["cover_url"], "甲\r\n乙"
        )

        status, _, page = self.save_via_form(crlf_track, title="CRLF 版本（改名）")
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(self.track_by_id(lf_track["id"])["cover_url"], "甲\n乙")
        self.assertEqual(
            self.track_by_id(crlf_track["id"])["cover_url"], "甲\r\n乙"
        )

    def test_empty_cover_stays_empty_when_untouched(self):
        track = self.create_track(
            title="原本无封面", source="/music/cover.flac", cover_url="",
        )
        status, _, page = self.save_via_form(track, title="改名仍无封面")
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(self.track_by_id(track["id"])["cover_url"], "")


class EditPageCoverChangesTest(ServerTestCase):
    """确实修改封面地址内部文字、空格或分行：按本次填写（LF）去首尾空白保存。"""

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="待改封面", source="/music/old.flac", duration=120,
            cover_url="https://img.example/old.png", description="原始说明",
        )
        self.track_id = self.track["id"]

    def submit_cover(self, cover_text, **changes):
        page = self.get_edit_page(self.track_id)
        fields = self.edit_fields_from_rendered_page(page)
        fields = self.form_with_field(fields, "cover_url", cover_text)
        for name, value in changes.items():
            fields = self.form_with_field(fields, name, value)
        return self.post_edit_form(self.track_id, fields)

    def test_edited_cover_saved_with_lf_newlines_and_trimmed(self):
        typed = "  https://img.example/第一段\r\n第二段  \r\n\r\n第三段\r\n "
        status, headers, page = self.submit_cover(typed)
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(
            headers["Location"], f"/?highlight={self.track_id}&edited=1"
        )
        # 内部换行统一为 LF，首尾空白去掉，内部文字、空格与空行保留。
        saved = "https://img.example/第一段\n第二段  \n\n第三段"
        record = self.track_by_id(self.track_id)
        self.assertEqual(record["cover_url"], saved)
        # 接口随后读到的地址与保存结果一致，标识不变、不新增记录。
        self.assertEqual(record["id"], self.track_id)
        self.assertEqual(len(self.list_tracks()), 1)
        # 重新打开编辑页，地址框呈现保存后的完整文字。
        self.assertEqual(parse_cover_box(self.get_edit_page(self.track_id)), saved)

    def test_internal_spaces_and_lines_are_preserved(self):
        typed = "https://img.example/a b\n  带空格的行  \n末行"
        status, _, page = self.submit_cover(typed)
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(
            self.track_by_id(self.track_id)["cover_url"],
            "https://img.example/a b\n  带空格的行  \n末行",
        )

    def test_clearing_cover_saves_empty_string(self):
        # 主动删空，或只留下空白（含换行），都保存为空字符串，不要求补填。
        for blank in ("", "   \r\n  \t "):
            with self.subTest(blank=repr(blank)):
                track = self.create_track(
                    title=f"清空封面 {blank!r}", source=f"/music/cl/{len(blank)}.flac",
                    cover_url="https://img.example/x.png",
                )
                status, _, page = self.submit_cover_to(track["id"], blank)
                self.assertEqual(status, 303, page[:500])
                self.assertEqual(
                    self.track_by_id(track["id"])["cover_url"], ""
                )
                # 重新打开编辑页与列表接口都看到空地址。
                self.assertEqual(
                    parse_cover_box(self.get_edit_page(track["id"])), ""
                )

    def submit_cover_to(self, track_id, cover_text):
        page = self.get_edit_page(track_id)
        fields = self.edit_fields_from_rendered_page(page)
        fields = self.form_with_field(fields, "cover_url", cover_text)
        return self.post_edit_form(track_id, fields)

    def test_filling_previously_empty_cover_succeeds(self):
        track = self.create_track(
            title="原本无封面", source="/music/empty.flac", cover_url="",
        )
        page = self.get_edit_page(track["id"])
        fields = self.edit_fields_from_rendered_page(page)
        fields = self.form_with_field(
            fields, "cover_url", "https://img.example/fill.png"
        )
        status, _, resp = self.post_edit_form(track["id"], fields)
        self.assertEqual(status, 303, resp[:500])
        self.assertEqual(
            self.track_by_id(track["id"])["cover_url"],
            "https://img.example/fill.png",
        )

    def test_other_valid_fields_save_together_with_changed_cover(self):
        status, _, page = self.submit_cover(
            "https://img.example/new.png\n第二行",
            title="改了名称和封面", duration="240",
        )
        self.assertEqual(status, 303, page[:500])
        record = self.track_by_id(self.track_id)
        self.assertEqual(record["title"], "改了名称和封面")
        self.assertEqual(record["duration"], 240)
        self.assertEqual(
            record["cover_url"], "https://img.example/new.png\n第二行"
        )
        # 未提交给页面以外的资料仍保留原值。
        self.assertEqual(record["description"], "原始说明")


class EditPageCoverSaveFailureTest(ServerTestCase):
    """时长等错误或来源冲突导致保存失败：记录不变，地址按本次填写回填。"""

    CRLF_COVER = "https://img.example/第一段\r\n第二段\r\n第三段"

    def test_untouched_cover_survives_failure_reprint_and_retry(self):
        track = self.create_track(
            title="失败重试", source="/music/cover.flac", duration=120,
            cover_url=self.CRLF_COVER,
        )
        # 用户没碰地址框（框内文字按 CRLF 提交），只把时长填成负数。
        page = self.get_edit_page(track["id"])
        fields = self.edit_fields_from_rendered_page(page)
        fields = self.form_with_field(fields, "duration", "-5")
        fields = [
            (name, browser_newlines(value))
            if name in ("source", "cover_url", "description", "tags")
            else (name, value)
            for name, value in fields
        ]
        status, _, page = self.post_edit_form(track["id"], fields)
        self.assertEqual(status, 400)
        # 整条记录保持原样；地址框回填本次提交的文字（LF 呈现，不丢分行）。
        self.assertEqual(self.track_by_id(track["id"]), track)
        self.assertEqual(
            parse_cover_box(page), self.CRLF_COVER.replace("\r\n", "\n")
        )
        self.assert_form_values(page, duration="-5")

        # 只修正时长后继续保存：未改地址仍保留原 CRLF 原文。
        fields = self.edit_fields_from_rendered_page(page)
        fields = self.form_with_field(fields, "duration", "240")
        fields = [
            (name, browser_newlines(value))
            if name in ("source", "cover_url", "description", "tags")
            else (name, value)
            for name, value in fields
        ]
        status, _, page = self.post_edit_form(track["id"], fields)
        self.assertEqual(status, 303, page[:500])
        record = self.track_by_id(track["id"])
        self.assertEqual(record["cover_url"], self.CRLF_COVER)
        self.assertEqual(record["duration"], 240)

    def test_modified_cover_in_failed_save_is_reprinted_and_saved_on_retry(self):
        track = self.create_track(
            title="失败重试", source="/music/cover.flac", duration=120,
            cover_url="https://img.example/old.png",
        )
        typed = "https://img.example/改过\r\n第二段"
        page = self.get_edit_page(track["id"])
        fields = self.edit_fields_from_rendered_page(page)
        fields = self.form_with_field(fields, "cover_url", typed)
        fields = self.form_with_field(fields, "duration", "-5")
        status, _, page = self.post_edit_form(track["id"], fields)
        self.assertEqual(status, 400)
        self.assertEqual(self.track_by_id(track["id"]), track)
        # 确实改过的地址按本次填写回填（LF 呈现），不换回旧值、不丢分行。
        self.assertEqual(parse_cover_box(page), "https://img.example/改过\n第二段")

        fields = self.edit_fields_from_rendered_page(page)
        fields = self.form_with_field(fields, "duration", "240")
        fields = [
            (name, browser_newlines(value))
            if name in ("source", "cover_url", "description", "tags")
            else (name, value)
            for name, value in fields
        ]
        status, _, page = self.post_edit_form(track["id"], fields)
        self.assertEqual(status, 303, page[:500])
        record = self.track_by_id(track["id"])
        self.assertEqual(
            record["cover_url"], "https://img.example/改过\n第二段"
        )
        self.assertEqual(record["duration"], 240)

    def test_source_conflict_keeps_cover_submission_and_record_unchanged(self):
        track = self.create_track(
            title="本曲目", source="/music/mine.flac",
            cover_url="https://img.example/old.png",
        )
        self.create_track(title="占用者", source="/music/taken.flac")
        typed = "https://img.example/冲突时仍回填\n第二行"
        page = self.get_edit_page(track["id"])
        fields = self.edit_fields_from_rendered_page(page)
        fields = self.form_with_field(fields, "source", "/music/taken.flac")
        fields = self.form_with_field(fields, "cover_url", typed)
        status, _, page = self.post_edit_form(track["id"], fields)
        self.assertEqual(status, 409, page[:500])
        # 整条记录保持原样，地址框保留本次填写（含分行）。
        self.assertEqual(self.track_by_id(track["id"]), track)
        self.assertEqual(
            parse_cover_box(page), "https://img.example/冲突时仍回填\n第二行"
        )


class EditCoverApiCompatibilityTest(ServerTestCase):
    """直接走 JSON 接口收录/编辑封面地址：网页处理不改变接口的换行规则。"""

    def test_api_create_preserves_internal_newline_styles(self):
        for name, cover in (
            ("lf", "https://a/甲\n乙"),
            ("crlf", "https://a/甲\r\n乙"),
            ("cr", "https://a/甲\r乙"),
        ):
            with self.subTest(case=name):
                track = self.create_track(
                    title=f"接口地址-{name}", source=f"/music/{name}.flac",
                    cover_url=cover,
                )
                self.assertEqual(track["cover_url"], cover)
                self.assertEqual(
                    self.track_by_id(track["id"])["cover_url"], cover
                )

    def test_api_patch_cover_trims_outer_but_keeps_inner(self):
        track = self.create_track(
            title="接口编辑", source="/music/api.flac",
            cover_url="https://img.example/old.png",
        )
        status, body = self.patch(track["id"], {
            "cover_url": "  https://img.example/a\r\n  b  \r\n ",
        })
        self.assertEqual(status, 200, body)
        # 接口规则不变：只裁整段首尾空白（含末行尾部空白与最后的换行），
        # 内部换行写法（CRLF）与内部行首空格逐字节保留。
        self.assertEqual(
            body["cover_url"], "https://img.example/a\r\n  b"
        )

    def test_api_non_string_cover_rejected(self):
        track = self.create_track(
            title="类型错误", source="/music/type.flac",
            cover_url="https://img.example/old.png",
        )
        status, body = self.patch(track["id"], {"cover_url": 123})
        self.assertEqual(status, 400, body)
        self.assertEqual(body["field"], "cover_url")
        self.assertEqual(
            self.track_by_id(track["id"])["cover_url"],
            "https://img.example/old.png",
        )


class SourceApiNewlinePreservationTest(ServerTestCase):
    """接口收录与接口编辑：来源只去首尾空白，内部换行写法逐字节保留。"""

    def test_api_create_preserves_internal_newlines_verbatim(self):
        source = "第一段\r\n第二段\n第三段\r第四段"
        track = self.create_track(title="多行来源", source=source)
        self.assertEqual(track["source"], source)
        # 接口随后读到的来源与保存结果一致。
        self.assertEqual(self.track_by_id(track["id"])["source"], source)

    def test_api_create_strips_only_surrounding_whitespace(self):
        track = self.create_track(
            title="首尾空白", source="\n  内部  保留\r\n换行  \n",
        )
        self.assertEqual(track["source"], "内部  保留\r\n换行")

    def test_api_patch_preserves_internal_newlines_verbatim(self):
        track = self.create_track(title="待改", source="/music/old.flac")
        source = "新的\r\n来源\n文字"
        status, body = self.patch(track["id"], {"source": source})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["source"], source)
        self.assertEqual(self.track_by_id(track["id"])["source"], source)


class CreateDuplicateSourceApiTest(ServerTestCase):
    """收录接口（POST /api/tracks）：同一来源默认 409 拒绝，不写入不改旧记录。"""

    def setUp(self):
        super().setUp()
        self.first = self.create_track(
            title="夜航·首版",
            source="/music/yehang.flac",
            duration=243.5,
            cover_url="https://img.example/yehang.png",
            description="首版说明",
            tags=["民谣", "现场"],
        )
        self.second = self.create_track(
            title="夜航·重制",
            source="/music/yehang.flac",
            duration=250,
            cover_url="https://img.example/yehang-remaster.png",
            description="重制说明",
            tags=["民谣", "重制"],
            save_as_new_version=True,
        )
        self.bystander = self.create_track(
            title="无关曲目", source="/music/other.flac", duration=9,
        )

    def duplicate_payload(self, **overrides):
        payload = {
            "title": "夜航·候选版本",
            "source": " \t/music/yehang.flac\n ",
            "duration": 307.25,
            "cover_url": "https://img.example/candidate.png",
            "description": "候选说明\n与已有记录都不同",
            "tags": ["候选", "新编"],
        }
        payload.update(overrides)
        return payload

    def test_duplicate_source_without_flag_returns_409(self):
        # 来源仅首尾空白不同；名称、说明等资料完全不同也必须拒绝。
        status, body = self.server.request(
            "POST", "/api/tracks", self.duplicate_payload()
        )
        self.assertEqual(status, 409, body)
        self.assertEqual(body["field"], "source")
        # existing 列出该来源的全部已有记录，只含 id 与 title，
        # 按标识升序，不混入其他来源的曲目。
        self.assertEqual(body["existing"], [
            {"id": self.first["id"], "title": "夜航·首版"},
            {"id": self.second["id"], "title": "夜航·重制"},
        ])

    def test_explicit_false_is_also_rejected(self):
        status, body = self.server.request(
            "POST", "/api/tracks",
            self.duplicate_payload(save_as_new_version=False),
        )
        self.assertEqual(status, 409, body)
        self.assertEqual(
            [item["id"] for item in body["existing"]],
            [self.first["id"], self.second["id"]],
        )

    def test_existing_lists_every_version_in_id_order(self):
        # 该来源已有三个版本时，existing 仍要全部列出且按标识升序。
        third = self.create_track(
            title="夜航·现场版",
            source="/music/yehang.flac",
            save_as_new_version=True,
        )
        status, body = self.server.request(
            "POST", "/api/tracks", self.duplicate_payload()
        )
        self.assertEqual(status, 409, body)
        self.assertEqual(body["existing"], [
            {"id": self.first["id"], "title": "夜航·首版"},
            {"id": self.second["id"], "title": "夜航·重制"},
            {"id": third["id"], "title": "夜航·现场版"},
        ])

    def test_rejection_creates_nothing_and_changes_nothing(self):
        status, _ = self.server.request(
            "POST", "/api/tracks", self.duplicate_payload()
        )
        self.assertEqual(status, 409)

        tracks = self.list_tracks()
        # 拒绝没有新增任何记录。
        self.assertEqual(len(tracks), 3)
        self.assertEqual(
            [t["id"] for t in tracks],
            [self.first["id"], self.second["id"], self.bystander["id"]],
        )
        # 任一已有记录的资料都没有被候选资料覆盖或合并。
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)
        self.assertEqual(self.track_by_id(self.second["id"]), self.second)
        self.assertEqual(self.track_by_id(self.bystander["id"]), self.bystander)

    def test_other_sources_with_same_title_are_not_listed(self):
        # 同名但来源不同的曲目不属于该来源的冲突记录。
        same_title = self.create_track(
            title="夜航·首版", source="/music/different.flac",
        )
        status, body = self.server.request(
            "POST", "/api/tracks", self.duplicate_payload()
        )
        self.assertEqual(status, 409, body)
        existing_ids = {item["id"] for item in body["existing"]}
        self.assertNotIn(same_title["id"], existing_ids)
        self.assertNotIn(self.bystander["id"], existing_ids)


class CreateNewVersionApiTest(ServerTestCase):
    """收录接口：save_as_new_version=true 时独立新增版本并保存本次资料。"""

    def setUp(self):
        super().setUp()
        self.first = self.create_track(
            title="夜航·首版",
            source="/music/yehang.flac",
            duration=243.5,
            cover_url="https://img.example/yehang.png",
            description="首版说明",
            tags=["民谣", "现场"],
        )

    def test_flag_creates_independent_record_with_submitted_data(self):
        payload = {
            "title": "夜航·重制",
            # 仅首尾空白不同仍视为同一来源，但本次明确要求另存。
            "source": " \t/music/yehang.flac\n ",
            "duration": 250,
            "cover_url": "https://img.example/yehang-remaster.png",
            "description": "重制说明",
            "tags": ["民谣", "重制"],
            "save_as_new_version": True,
        }
        status, body = self.server.request("POST", "/api/tracks", payload)
        self.assertEqual(status, 201, body)
        self.assertIsInstance(body["id"], int)
        self.assertNotEqual(body["id"], self.first["id"])
        # 返回本次保存的完整曲目：来源按去首尾空白后的文字入库，
        # 其余资料全部来自本次提交，不继承旧版本。
        self.assertEqual(body, {
            "id": body["id"],
            "title": "夜航·重制",
            "source": "/music/yehang.flac",
            "duration": 250,
            "cover_url": "https://img.example/yehang-remaster.png",
            "description": "重制说明",
            "tags": ["民谣", "重制"],
        })

        tracks = self.list_tracks()
        # 列表中两个版本同时存在，按原有标识顺序展示。
        self.assertEqual([t["id"] for t in tracks],
                         [self.first["id"], body["id"]])
        self.assertEqual(self.track_by_id(body["id"]), body)
        # 原版本保持提交前的整条资料，没有被覆盖或合并。
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)

    def test_multiple_versions_coexist_with_independent_metadata(self):
        second = self.create_track(
            title="夜航·重制", source="/music/yehang.flac",
            duration=250, description="重制说明",
            save_as_new_version=True,
        )
        third = self.create_track(
            title="夜航·现场", source="/music/yehang.flac",
            duration=300.5, description="现场说明", tags=["现场"],
            save_as_new_version=True,
        )
        tracks = self.list_tracks()
        self.assertEqual(
            [t["id"] for t in tracks],
            [self.first["id"], second["id"], third["id"]],
        )
        self.assertEqual([t["title"] for t in tracks],
                         ["夜航·首版", "夜航·重制", "夜航·现场"])
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)

    def test_new_version_then_plain_duplicate_is_again_rejected(self):
        # 另存成功后，不带标记再次提交同一来源仍应被拒绝，
        # existing 此时包含两个版本。
        second = self.create_track(
            title="夜航·重制", source="/music/yehang.flac",
            save_as_new_version=True,
        )
        status, body = self.server.request("POST", "/api/tracks", {
            "title": "又一次提交",
            "source": "/music/yehang.flac",
        })
        self.assertEqual(status, 409, body)
        self.assertEqual(
            [item["id"] for item in body["existing"]],
            [self.first["id"], second["id"]],
        )
        self.assertEqual(len(self.list_tracks()), 2)


class CreateSourceDistinctionApiTest(ServerTestCase):
    """同名不同来源直接收录；来源只忽略首尾空白，不合并内部文字差异。"""

    def test_same_title_different_source_succeeds(self):
        first = self.create_track(title="同名曲目", source="/music/a.flac")
        status, body = self.server.request("POST", "/api/tracks", {
            "title": "同名曲目",
            "source": "/music/b.flac",
            "description": "来源不同，名称相同也不应被拦",
        })
        self.assertEqual(status, 201, body)
        self.assertNotEqual(body["id"], first["id"])
        self.assertEqual(len(self.list_tracks()), 2)

    def test_internal_text_differences_are_separate_sources(self):
        # 内部多一个空格、大小写不同都不是同一来源；不勾选另存也直接成功。
        base = self.create_track(title="内部空格", source="/music/a b.flac")
        status, double_space = self.server.request("POST", "/api/tracks", {
            "title": "内部两个空格",
            "source": "/music/a  b.flac",
        })
        self.assertEqual(status, 201, double_space)

        status, upper = self.server.request("POST", "/api/tracks", {
            "title": "大小写不同",
            "source": "/music/A B.FLAC",
        })
        self.assertEqual(status, 201, upper)
        tracks = self.list_tracks()
        self.assertEqual(len(tracks), 3)
        self.assertEqual(
            {t["source"] for t in tracks},
            {"/music/a b.flac", "/music/a  b.flac", "/music/A B.FLAC"},
        )
        # 内部文字不同的两条各自拿到独立标识，没有并回原始记录。
        self.assertNotEqual(base["id"], double_space["id"])
        self.assertNotEqual(base["id"], upper["id"])
        self.assertNotEqual(double_space["id"], upper["id"])

    def test_only_leading_and_trailing_whitespace_is_ignored(self):
        # 对照组：仅首尾空白不同的来源仍判为重复。
        self.create_track(title="原始", source="/music/trim.flac")
        status, body = self.server.request("POST", "/api/tracks", {
            "title": "首尾空白版本",
            "source": "\t\n/music/trim.flac  \r\n",
        })
        self.assertEqual(status, 409, body)
        self.assertEqual(len(body["existing"]), 1)


class LegacyTrackCreateTest(ServerTestCase):
    """只有标识与名称、来源缺失的旧记录不参加收录判重。"""

    def setUp(self):
        super().setUp()
        self.legacy_a = self.server.insert_legacy("旧记录·同名")
        self.legacy_b = self.server.insert_legacy("另一条旧记录")

    def test_same_title_as_legacy_does_not_block_create(self):
        # 旧记录没有来源，即使名称完全相同也不能拦住新收录。
        status, body = self.server.request("POST", "/api/tracks", {
            "title": "旧记录·同名",
            "source": "/music/new.flac",
            "description": "全新来源的同名曲目",
        })
        self.assertEqual(status, 201, body)

        tracks = self.list_tracks()
        self.assertEqual(
            [t["id"] for t in tracks],
            [self.legacy_a, self.legacy_b, body["id"]],
        )
        # 两条旧记录仍是只有标识与名称、来源缺失的状态。
        for legacy_id in (self.legacy_a, self.legacy_b):
            record = self.track_by_id(legacy_id)
            self.assertIsNone(record["source"])
        self.assertEqual(self.track_by_id(body["id"])["source"], "/music/new.flac")

    def test_legacy_records_never_appear_in_existing(self):
        # 新来源恰好与任何名称无关：冲突列表中也绝不可能出现旧记录。
        self.create_track(title="占位", source="/music/taken.flac")
        status, body = self.server.request("POST", "/api/tracks", {
            "title": "旧记录·同名",
            "source": "/music/taken.flac",
        })
        self.assertEqual(status, 409, body)
        existing_ids = {item["id"] for item in body["existing"]}
        self.assertNotIn(self.legacy_a, existing_ids)
        self.assertNotIn(self.legacy_b, existing_ids)


class SaveAsNewVersionTypeValidationTest(ServerTestCase):
    """save_as_new_version 只接受布尔值：字符串/数字一律 400 且不写入。"""

    def setUp(self):
        super().setUp()
        self.existing = self.create_track(
            title="已存在", source="/music/taken.flac",
        )

    def test_non_bool_values_against_duplicate_source_are_400(self):
        for bad in ("true", "false", "1", "0", "yes", 1, 0):
            with self.subTest(bad=bad):
                status, body = self.server.request("POST", "/api/tracks", {
                    "title": "试图靠字符串/数字蒙混另存",
                    "source": "/music/taken.flac",
                    "save_as_new_version": bad,
                })
                self.assertEqual(status, 400, body)
                # 必须指出出错的就是该字段。
                self.assertEqual(body["field"], "save_as_new_version")
                self.assertIn("save_as_new_version", body["error"])
                # 既没有把 "true"/1 当作同意另存，也没有写入任何新曲目。
                self.assertEqual(len(self.list_tracks()), 1)
                self.assertEqual(
                    self.track_by_id(self.existing["id"]), self.existing
                )

    def test_non_bool_value_against_free_source_is_also_400(self):
        # 即使来源不重复，类型校验仍然生效，不会静默收录。
        status, body = self.server.request("POST", "/api/tracks", {
            "title": "全新来源",
            "source": "/music/fresh.flac",
            "save_as_new_version": "true",
        })
        self.assertEqual(status, 400, body)
        self.assertEqual(body["field"], "save_as_new_version")
        tracks = self.list_tracks()
        self.assertEqual([t["id"] for t in tracks], [self.existing["id"]])
        self.assertFalse(
            any(t["source"] == "/music/fresh.flac" for t in tracks)
        )


class HomeCreateConflictTest(ServerTestCase):
    """首页收录表单：重复来源被拒时展示冲突记录并保留本次填写。"""

    def setUp(self):
        super().setUp()
        self.first = self.create_track(
            title="夜航·首版",
            source="/music/yehang.flac",
            duration=243.5,
            cover_url="https://img.example/yehang.png",
            description="首版说明",
            tags=["民谣", "现场"],
        )
        self.second = self.create_track(
            title="夜航·重制",
            source="/music/yehang.flac",
            duration=250,
            tags=["民谣", "重制"],
            save_as_new_version=True,
        )
        self.bystander = self.create_track(
            title="无关曲目", source="/music/other.flac",
        )

    def candidate_fields(self, *, save_as_new_version=False):
        return self.create_form_fields(
            title="夜航·候选版本",
            source=" \t/music/yehang.flac\n ",
            duration="307.25",
            cover_url="https://img.example/candidate.png",
            description="候选说明\n第二行",
            tags="候选,新编",
            save_as_new_version=save_as_new_version,
        )

    def test_duplicate_shows_conflicts_and_reprints_form(self):
        status, headers, page = self.post_create_form(self.candidate_fields())
        self.assertEqual(status, 409, page[:500])

        # 冲突横幅列出该来源全部已有记录（标识与名称，标识升序），
        # 不含其他来源的曲目；并提示可勾选“另存为新版本”。
        self.assertEqual(parse_conflict_items(page), [
            (self.first["id"], "夜航·首版"),
            (self.second["id"], "夜航·重制"),
        ])
        banner = strip_tags(CONFLICT_BANNER_RE.search(page).group(1))
        self.assertIn("另存为新版本", banner)

        # 本次填写的各项资料逐字段保留，方便辨认后决定是否另存。
        self.assert_form_values(
            page,
            title="夜航·候选版本",
            source=" \t/music/yehang.flac\n ",
            duration="307.25",
            cover_url="https://img.example/candidate.png",
            description="候选说明\n第二行",
        )
        self.assertEqual(parse_input_value(page, "tags", "tags"), "候选,新编")
        # 未勾选另存时，重绘页面上的勾选框也不应被偷偷选中。
        checkbox = FORCE_CHECKBOX_RE.search(page)
        self.assertIsNotNone(checkbox)
        self.assertNotIn("checked", checkbox.group(0))

    def test_rejected_form_creates_nothing_and_changes_nothing(self):
        status, _, _ = self.post_create_form(self.candidate_fields())
        self.assertEqual(status, 409)

        tracks = self.list_tracks()
        self.assertEqual(
            [t["id"] for t in tracks],
            [self.first["id"], self.second["id"], self.bystander["id"]],
        )
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)
        self.assertEqual(self.track_by_id(self.second["id"]), self.second)
        self.assertEqual(self.track_by_id(self.bystander["id"]), self.bystander)

    def test_checking_save_as_new_version_creates_record(self):
        # 第一次未勾选：409 拒绝。
        status, _, _ = self.post_create_form(self.candidate_fields())
        self.assertEqual(status, 409)

        # 用户辨认已有记录后勾选“另存为新版本”，用同样的资料再次保存。
        status, headers, page = self.post_create_form(
            self.candidate_fields(save_as_new_version=True),
        )
        self.assertEqual(status, 303, page[:500])
        match = re.search(r"highlight=(\d+)$", headers["Location"])
        self.assertIsNotNone(match, headers["Location"])
        new_id = int(match.group(1))
        self.assertNotIn(new_id, (self.first["id"], self.second["id"]))

        # 成功后重定向回列表：成功提示与新曲目同时出现，顺序按标识升序。
        status, _, listing_page = self.get_home_with_query(
            headers["Location"]
        )
        self.assertEqual(status, 200)
        success = strip_tags(BANNER_SUCCESS_RE.search(listing_page).group(1))
        self.assertIn("收录成功", success)
        self.assertIn(f"#{new_id}", success)
        # 列表按标识升序展示全部曲目，包含同一来源的三个版本与无关曲目。
        self.assertEqual(parse_listed_tracks(listing_page), [
            (self.first["id"], "夜航·首版"),
            (self.second["id"], "夜航·重制"),
            (self.bystander["id"], "无关曲目"),
            (new_id, "夜航·候选版本"),
        ])
        # 同一来源的三个版本同时存在，且按原有标识顺序展示。
        same_source = [
            (tid, title)
            for tid, title in parse_listed_tracks(listing_page)
            if tid in (self.first["id"], self.second["id"], new_id)
        ]
        self.assertEqual(same_source, [
            (self.first["id"], "夜航·首版"),
            (self.second["id"], "夜航·重制"),
            (new_id, "夜航·候选版本"),
        ])

        # 新记录使用独立标识，保存的是本次提交的资料；旧版本原样保留。
        new_record = self.track_by_id(new_id)
        self.assertEqual(new_record, {
            "id": new_id,
            "title": "夜航·候选版本",
            "source": "/music/yehang.flac",
            "duration": 307.25,
            "cover_url": "https://img.example/candidate.png",
            "description": "候选说明\n第二行",
            "tags": ["候选", "新编"],
        })
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)
        self.assertEqual(self.track_by_id(self.second["id"]), self.second)

    def get_home_with_query(self, target):
        # target 形如 /?highlight=N，直接走 GET 原始请求。
        return self.server.get_page(target)

    def test_fresh_source_form_succeeds_without_checkbox(self):
        # 同名但来源不同：首页普通收录直接成功。
        fields = self.create_form_fields(
            title="夜航·首版",
            source="/music/different.flac",
            duration="12",
            tags="同名",
        )
        status, headers, page = self.post_create_form(fields)
        self.assertEqual(status, 303, page[:500])
        new_id = int(re.search(r"highlight=(\d+)$", headers["Location"]).group(1))
        record = self.track_by_id(new_id)
        self.assertEqual(record["source"], "/music/different.flac")
        self.assertEqual(record["title"], "夜航·首版")
        self.assertEqual(record["duration"], 12)
        self.assertEqual(record["tags"], ["同名"])
        # 原有三条记录一条没少。
        self.assertEqual(len(self.list_tracks()), 4)

    def test_internal_source_difference_form_succeeds(self):
        # 来源内部文字差异不被额外合并：不勾选另存也应直接收录。
        status, headers, page = self.post_create_form(
            self.create_form_fields(
                title="内部空格不同", source="/music/yehang.flac 二次",
            )
        )
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(len(self.list_tracks()), 4)


class CreateRequiredFieldApiTest(ServerTestCase):
    """收录接口：名称/来源缺失或不合法时 400 且不产生不完整记录。

    所有用例的来源都使用尚未收录的文字，使失败明确属于必填资料错误，
    而不是来源重复冲突（409）。
    """

    # 与出错必填项一起提交的选填资料全部合法：即使如此也整单不写入。
    OPTIONAL_FIELDS = {
        "duration": 243.5,
        "cover_url": "https://img.example/candidate.png",
        "description": "候选说明：中文、换行\n第二行",
        "tags": ["候选", "新编"],
    }
    VALID_TITLE = "山涧晨曲"
    # 每次按用例名派生未收录来源，避免任何子例之间发生来源重复。
    SOURCE_COUNTER = 0

    def bad_payload(self, field, bad_value, *, with_optional):
        payload = {"title": self.VALID_TITLE, "source": self.free_source()}
        payload[field] = bad_value
        if with_optional:
            payload.update(self.OPTIONAL_FIELDS)
        return payload

    def free_source(self):
        CreateRequiredFieldApiTest.SOURCE_COUNTER += 1
        return f"/music/required-{CreateRequiredFieldApiTest.SOURCE_COUNTER}.flac"

    def assert_required_error(self, status, body, field, label):
        self.assertEqual(status, 400, body)
        # field 指向出错的那个必填字段。
        self.assertEqual(body["field"], field)
        # 错误文字说明该字段不合法（含其中文名称）。
        self.assertIn(label, body["error"])
        # 绝不是来源重复冲突的响应。
        self.assertNotIn("existing", body)

    def assert_nothing_saved(self):
        # 失败不能产生一条不完整的曲目。
        self.assertEqual(self.list_tracks(), [])

    def assert_cases_for_field(self, field, label, bad_values):
        for bad in bad_values:
            with self.subTest(field=field, bad=repr(bad)):
                payload = self.bad_payload(field, bad, with_optional=True)
                status, body = self.server.request(
                    "POST", "/api/tracks", payload
                )
                self.assert_required_error(status, body, field, label)
                self.assert_nothing_saved()

    def test_title_missing_null_blank_and_non_strings_are_rejected(self):
        # 省略名称、null、空字符串、只有空白的字符串，以及数字、布尔值、
        # 数组、对象：另一项（来源）与全部选填资料合法也不能写入。
        bad_values = [None, "", " ", "\t", " \n\t\r ",
                      0, 1, 243.5, False, True, [], ["名称"], {}, {"a": 1}]
        self.assert_cases_for_field("title", "名称", bad_values)

    def test_source_missing_null_blank_and_non_strings_are_rejected(self):
        bad_values = [None, "", " ", "\t", "  \t\n ",
                      0, 3, 243.5, False, True, [], ["/x"], {}, {"a": 1}]
        self.assert_cases_for_field("source", "来源", bad_values)

    def test_omitted_field_omits_the_key_entirely(self):
        # “省略”必须是请求里根本没有该键，而不是提交 null；两种形态都拒绝。
        for field, label in (("title", "名称"), ("source", "来源")):
            with self.subTest(field=field):
                payload = {"title": self.VALID_TITLE, "source": self.free_source()}
                del payload[field]
                status, body = self.server.request(
                    "POST", "/api/tracks", payload
                )
                self.assert_required_error(status, body, field, label)
                self.assert_nothing_saved()

    def test_optional_only_payloads_with_one_bad_required_are_atomic(self):
        # 每次只让一个必填字段出错；合法的另一项与选填资料不先写入。
        # 这里覆盖“出错字段给字符串类型但为空白”与“类型错误”两类，
        # 并显式断言数据库没有新增记录。
        cases = [
            ("title", "   "), ("title", 123), ("title", True),
            ("title", []), ("title", {}),
            ("source", "\t\n"), ("source", 456), ("source", False),
            ("source", []), ("source", {}),
        ]
        for field, bad in cases:
            with self.subTest(field=field, bad=repr(bad)):
                payload = self.bad_payload(field, bad, with_optional=True)
                status, body = self.server.request(
                    "POST", "/api/tracks", payload
                )
                self.assertEqual(status, 400, body)
                self.assertEqual(body["field"], field)
                self.assert_nothing_saved()

    def test_chinese_title_and_source_with_chinese_path_are_saved(self):
        # 有效收录对照：中文名称、含中文目录的来源可以保存；首尾空白被
        # 去掉，内部文字与标点（含连续空格）原样保留。
        payload = {
            "title": "  夜航·前奏（live）  ",
            "source": "\t/音乐/现场 录音/夜航 序曲.flac\n",
        }
        status, body = self.server.request("POST", "/api/tracks", payload)
        self.assertEqual(status, 201, body)
        self.assertEqual(body["title"], "夜航·前奏（live）")
        self.assertEqual(body["source"], "/音乐/现场 录音/夜航 序曲.flac")
        # 省略选填资料仍按既有默认结果保存：时长未知、封面和说明为空、
        # 标签为空数组。
        self.assertIsNone(body["duration"])
        self.assertEqual(body["cover_url"], "")
        self.assertEqual(body["description"], "")
        self.assertEqual(body["tags"], [])
        # 成功响应与随后列表读到的记录一致。
        tracks = self.list_tracks()
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0], body)

    def test_valid_create_with_all_optional_fields_round_trips(self):
        # 第二个对照：选填资料齐全的有效收录同样成功，防止上面的拒绝
        # 用例把合法资料也误伤。
        payload = {
            "title": "晨曲",
            "source": self.free_source(),
            **self.OPTIONAL_FIELDS,
        }
        status, body = self.server.request("POST", "/api/tracks", payload)
        self.assertEqual(status, 201, body)
        self.assertEqual(self.track_by_id(body["id"]), body)
        self.assertEqual(len(self.list_tracks()), 1)


class CreateRequiredFieldApiWithExistingTest(ServerTestCase):
    """已有曲库时必填资料失败：已有记录完整保留，顺序与数量不变。"""

    def setUp(self):
        super().setUp()
        self.first = self.create_track(
            title="已有曲目·甲",
            source="/music/existing-a.flac",
            duration=12,
            cover_url="https://img.example/a.png",
            description="甲的说明\n第二行",
            tags=["民谣", "现场"],
        )
        self.second = self.create_track(
            title="已有曲目·乙",
            source="/music/existing-b.flac",
            duration=None,
            description="",
            tags=[],
        )
        self.expected_ids = [self.first["id"], self.second["id"]]

    def assert_library_unchanged(self):
        tracks = self.list_tracks()
        # 记录数量不增加，列表顺序不变，已有记录完整资料不被改动。
        self.assertEqual([t["id"] for t in tracks], self.expected_ids)
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)
        self.assertEqual(self.track_by_id(self.second["id"]), self.second)

    def test_bad_title_requests_leave_library_untouched(self):
        for bad in (None, "", "  \t ", 7, True, [], {}):
            with self.subTest(bad=repr(bad)):
                payload = {
                    "title": bad,
                    "source": "/music/fresh-title-case.flac",
                    "duration": 99,
                    "description": "不应保存的说明",
                    "tags": ["不应保存"],
                }
                status, body = self.server.request(
                    "POST", "/api/tracks", payload
                )
                self.assertEqual(status, 400, body)
                self.assertEqual(body["field"], "title")
                self.assertIn("名称", body["error"])
                self.assert_library_unchanged()

    def test_bad_source_requests_leave_library_untouched(self):
        for bad in (None, "", "\n\t ", 7, False, [], {}):
            with self.subTest(bad=repr(bad)):
                payload = {
                    "title": "候选名称",
                    "source": bad,
                    "duration": 99,
                    "cover_url": "https://img.example/new.png",
                    "description": "不应保存的说明",
                    "tags": ["候选"],
                }
                status, body = self.server.request(
                    "POST", "/api/tracks", payload
                )
                self.assertEqual(status, 400, body)
                self.assertEqual(body["field"], "source")
                self.assertIn("来源", body["error"])
                self.assert_library_unchanged()

    def test_valid_create_after_failures_extends_library(self):
        # 多次必填失败后，一次有效收录仍能成功，接在已有记录之后。
        for bad in ("", "   "):
            status, _ = self.server.request("POST", "/api/tracks", {
                "title": bad, "source": "/music/never-written.flac",
            })
            self.assertEqual(status, 400)
        self.assert_library_unchanged()

        status, body = self.server.request("POST", "/api/tracks", {
            "title": "补收录的曲目", "source": "/music/after-failures.flac",
        })
        self.assertEqual(status, 201, body)
        self.assertEqual(
            [t["id"] for t in self.list_tracks()],
            self.expected_ids + [body["id"]],
        )
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)
        self.assertEqual(self.track_by_id(self.second["id"]), self.second)


class CreateDurationValidApiTest(ServerTestCase):
    """收录接口（POST /api/tracks）：合法时长随本次资料保存，0 与未知分清。

    名称与来源合法、来源尚未收录时：有限的非负整数与小数都能作为秒数
    保存，成功返回 201 与完整曲目；省略时长或明确提交 null 都表示未知。
    随后读取曲目列表，同一标识下读到同一秒数或未知状态，名称、来源与
    本次提交的其他合法资料一致；列表按标识升序，新收录不改变已有曲目。
    """

    def full_payload(self, source, duration, **overrides):
        payload = {
            "title": "夜航·现场收录",
            "source": source,
            "duration": duration,
            "cover_url": "https://img.example/yehang.png",
            "description": "现场录音\n第二行：中文标点，保留",
            "tags": ["民谣", "现场", "民谣"],
        }
        payload.update(overrides)
        return payload

    def assert_created_and_listed(self, payload, expected_duration):
        status, body = self.server.request("POST", "/api/tracks", payload)
        self.assertEqual(status, 201, body)
        self.assertIsInstance(body["id"], int)
        # 成功返回完整曲目：时长为本次秒数，标签按既有规则裁剪去重，
        # 其余资料全部来自本次提交。
        self.assertEqual(body, {
            "id": body["id"],
            "title": payload["title"],
            "source": payload["source"],
            "duration": expected_duration,
            "cover_url": payload["cover_url"],
            "description": payload["description"],
            "tags": ["民谣", "现场"],
        })
        # 随后读取曲目列表：同一标识下读到同一时长与整条资料。
        self.assertEqual(self.track_by_id(body["id"]), body)
        return body

    def test_integer_seconds_saved_as_integer(self):
        record = self.assert_created_and_listed(
            self.full_payload("/music/int-seconds.flac", 307), 307
        )
        # 整数值在响应与列表中都按整数呈现，不变成 307.0。
        self.assertIsInstance(record["duration"], int)

    def test_decimal_seconds_saved_without_rounding_or_conversion(self):
        # 有限非负小数按秒原样保存，不换算分钟、不四舍五入、不截断成整数。
        record = self.assert_created_and_listed(
            self.full_payload("/music/decimal-seconds.flac", 243.5), 243.5
        )
        self.assertIsInstance(record["duration"], float)

    def test_small_decimal_seconds_saved(self):
        for seconds in (0.5, 0.25, 12.75):
            with self.subTest(seconds=seconds):
                record = self.assert_created_and_listed(
                    self.full_payload(
                        f"/music/decimal-{seconds}.flac", seconds,
                        title=f"小数秒 {seconds}",
                    ),
                    seconds,
                )
                self.assertEqual(record["duration"], seconds)

    def test_zero_is_known_duration_not_unknown(self):
        # 0 是合法的已知时长：读回必须是数字 0，绝不能变成 null。
        record = self.assert_created_and_listed(
            self.full_payload(
                "/music/zero.flac", 0,
                description="开头静音\n0 秒前奏",
            ),
            0,
        )
        self.assertEqual(record["duration"], 0)
        self.assertIsNotNone(record["duration"])
        self.assertIsInstance(record["duration"], int)

    def test_omitted_duration_saved_as_unknown(self):
        payload = {
            "title": "未知时长曲目",
            "source": "/music/omitted-duration.flac",
            "cover_url": "https://img.example/unknown.png",
            "description": "时长待补",
            "tags": ["待补"],
        }
        status, body = self.server.request("POST", "/api/tracks", payload)
        self.assertEqual(status, 201, body)
        # 省略时长表示未知：成功记录中的时长为 null，不是 0。
        self.assertIsNone(body["duration"])
        self.assertEqual(body, {
            "id": body["id"],
            "title": "未知时长曲目",
            "source": "/music/omitted-duration.flac",
            "duration": None,
            "cover_url": "https://img.example/unknown.png",
            "description": "时长待补",
            "tags": ["待补"],
        })
        self.assertIsNone(self.track_by_id(body["id"])["duration"])

    def test_explicit_null_saved_as_unknown(self):
        # 明确提交 null 与省略时长语义相同，都表示未知。
        payload = {
            "title": "显式未知曲目",
            "source": "/music/null-duration.flac",
            "duration": None,
        }
        status, body = self.server.request("POST", "/api/tracks", payload)
        self.assertEqual(status, 201, body)
        self.assertIsNone(body["duration"])
        self.assertEqual(self.track_by_id(body["id"]), body)

    def test_known_and_unknown_distinct_records_coexist_in_id_order(self):
        # 连续收录：已知整数、已知小数、0、未知各一条，验证列表按标识
        # 升序展示，各标识的时长状态互不串扰。
        known_int = self.assert_created_and_listed(
            self.full_payload("/music/order-int.flac", 307,
                              title="顺序·整数"),
            307,
        )
        unknown = self.server.create_track(
            title="顺序·未知", source="/music/order-unknown.flac",
        )
        self.assertIsNone(unknown["duration"])
        zero = self.assert_created_and_listed(
            self.full_payload("/music/order-zero.flac", 0,
                              title="顺序·零"),
            0,
        )
        decimal = self.assert_created_and_listed(
            self.full_payload("/music/order-decimal.flac", 243.5,
                              title="顺序·小数"),
            243.5,
        )
        tracks = self.list_tracks()
        self.assertEqual(
            [t["id"] for t in tracks],
            [known_int["id"], unknown["id"], zero["id"], decimal["id"]],
        )
        self.assertEqual(
            [t["duration"] for t in tracks],
            [307, None, 0, 243.5],
        )

    def test_new_create_does_not_change_existing_records(self):
        # 新增曲目不改变已有曲目的资料，列表仍按标识升序。
        first = self.create_track(
            title="已有曲目·甲",
            source="/music/existing-a.flac",
            duration=12,
            cover_url="https://img.example/a.png",
            description="甲的说明\n第二行",
            tags=["民谣"],
        )
        second = self.create_track(
            title="已有曲目·乙", source="/music/existing-b.flac",
            duration=None,
        )
        before_ids = [first["id"], second["id"]]

        new_record = self.assert_created_and_listed(
            self.full_payload("/music/existing-c.flac", 95.5,
                              title="已有曲目·丙"),
            95.5,
        )
        tracks = self.list_tracks()
        self.assertEqual(
            [t["id"] for t in tracks], before_ids + [new_record["id"]]
        )
        self.assertEqual(self.track_by_id(first["id"]), first)
        self.assertEqual(self.track_by_id(second["id"]), second)


class CreateDurationInvalidApiTest(ServerTestCase):
    """收录接口：时长非法时 400 且 field=duration，整单不写入。

    时长为负数或非有限数值，或写成字符串、布尔值、数组、对象时拒绝；
    数字字符串即使看起来像合法秒数也不自动转换，false 不能变成 0。
    其他资料都合法也不能保存部分内容：空曲库仍为空，已有曲库的记录
    数量、顺序与各条完整资料保持提交前状态。
    """

    # 与非法时长一起提交的其他资料全部合法：即使如此也整单不写入。
    def full_payload(self, source, duration):
        return {
            "title": "夜航·候选",
            "source": source,
            "duration": duration,
            "cover_url": "https://img.example/candidate.png",
            "description": "候选说明：中文、换行\n第二行",
            "tags": ["候选", "新编"],
        }

    def assert_duration_rejected(self, payload):
        status, body = self.server.request("POST", "/api/tracks", payload)
        self.assertEqual(status, 400, body)
        # field 指向 duration，错误文字说明时长有误；不是来源冲突响应。
        self.assertEqual(body["field"], "duration")
        self.assertIn("时长", body["error"])
        self.assertNotIn("existing", body)

    def test_negative_numbers_are_rejected(self):
        for bad in (-1, -0.01, -243.5):
            with self.subTest(bad=bad):
                self.assert_duration_rejected(
                    self.full_payload(f"/music/neg-{bad}.flac", bad)
                )
                self.assertEqual(self.list_tracks(), [])

    def test_non_finite_values_are_rejected(self):
        # NaN、Infinity、-Infinity 以及解析后溢出为 Infinity 的指数写法，
        # 都是非有限数值（通过原始 JSON 文本发送），不能保存。
        for raw_fragment in ("NaN", "Infinity", "-Infinity", "1e999",
                             "-1e999"):
            with self.subTest(raw=raw_fragment):
                status, body = self.post_raw(
                    '{"title": "夜航·候选", '
                    f'"source": "/music/nonfinite-{raw_fragment}.flac", '
                    f'"duration": {raw_fragment}, '
                    '"description": "不应保存的说明"}'
                )
                self.assertEqual(status, 400, body)
                self.assertEqual(body["field"], "duration")
                self.assertIn("时长", body["error"])
                self.assertEqual(self.list_tracks(), [])

    def test_numeric_strings_are_rejected_without_coercion(self):
        # 数字文字即使看起来是合法秒数也不能自动转换成数字；
        # 网页允许在输入框里填写数字文字，不改变 JSON 接口对数字类型的要求。
        for bad in ("243", "243.5", "0", "-1", " 12 ", ""):
            with self.subTest(bad=repr(bad)):
                self.assert_duration_rejected(
                    self.full_payload(f"/music/str-{bad!r}.flac", bad)
                )
                self.assertEqual(self.list_tracks(), [])

    def test_boolean_is_rejected_without_becoming_zero_or_one(self):
        # false 不能变成 0，true 也不能变成 1。
        for bad in (False, True):
            with self.subTest(bad=bad):
                self.assert_duration_rejected(
                    self.full_payload(f"/music/bool-{bad}.flac", bad)
                )
                self.assertEqual(self.list_tracks(), [])

    def test_array_and_object_are_rejected(self):
        for bad in ([], [243.5], {}, {"seconds": 243.5}):
            with self.subTest(bad=bad):
                self.assert_duration_rejected(
                    self.full_payload(f"/music/complex-{type(bad).__name__}.flac", bad)
                )
                self.assertEqual(self.list_tracks(), [])

    def test_other_scalar_types_are_rejected(self):
        for bad in ("abc", "null", "NaN"):
            with self.subTest(bad=repr(bad)):
                self.assert_duration_rejected(
                    self.full_payload(f"/music/text-{bad}.flac", bad)
                )
                self.assertEqual(self.list_tracks(), [])

    def test_zero_accepted_but_string_zero_rejected(self):
        # 对照保障：数字 0 正常收录，而字符串 "0" 被拒绝，二者不能混淆。
        status, body = self.server.request(
            "POST", "/api/tracks",
            self.full_payload("/music/real-zero.flac", 0),
        )
        self.assertEqual(status, 201, body)
        self.assertEqual(body["duration"], 0)

        self.assert_duration_rejected(
            self.full_payload("/music/string-zero.flac", "0")
        )
        # 字符串 "0" 没有产生第二条记录。
        tracks = self.list_tracks()
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["source"], "/music/real-zero.flac")
        self.assertEqual(tracks[0]["duration"], 0)


class CreateDurationInvalidWithExistingApiTest(ServerTestCase):
    """已有曲库时收录接口时长失败：数量、顺序与各条完整资料保持原样。"""

    def setUp(self):
        super().setUp()
        self.first = self.create_track(
            title="已有曲目·甲",
            source="/music/existing-a.flac",
            duration=12,
            cover_url="https://img.example/a.png",
            description="甲的说明\n第二行",
            tags=["民谣"],
        )
        self.second = self.create_track(
            title="已有曲目·乙",
            source="/music/existing-b.flac",
            duration=33.3,
            description="",
            tags=["现场"],
        )
        self.bystander = self.create_track(
            title="无关曲目", source="/music/other.flac", duration=None,
        )
        self.expected_ids = [
            self.first["id"], self.second["id"], self.bystander["id"],
        ]

    def full_payload(self, source, duration):
        return {
            "title": "不应收录的候选",
            "source": source,
            "duration": duration,
            "cover_url": "https://img.example/candidate.png",
            "description": "不应保存的候选说明\n第二行",
            "tags": ["候选", "新编"],
        }

    def assert_library_unchanged(self):
        tracks = self.list_tracks()
        # 记录数量不增加，顺序仍是标识升序。
        self.assertEqual([t["id"] for t in tracks], self.expected_ids)
        # 各条完整资料保持提交前状态，不能留下只有名称或来源的残缺记录。
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)
        self.assertEqual(self.track_by_id(self.second["id"]), self.second)
        self.assertEqual(
            self.track_by_id(self.bystander["id"]), self.bystander
        )

    def test_every_invalid_shape_leaves_library_untouched(self):
        cases = [
            ("dict", -1),
            ("dict", -0.25),
            ("dict", "243.5"),
            ("dict", "0"),
            ("dict", False),
            ("dict", True),
            ("dict", []),
            ("dict", {}),
            ("raw", "NaN"),
            ("raw", "Infinity"),
            ("raw", "-Infinity"),
            ("raw", "1e999"),
        ]
        for index, (kind, value) in enumerate(cases):
            with self.subTest(value=value):
                source = f"/music/fresh-duration-case-{index}.flac"
                if kind == "dict":
                    status, body = self.server.request(
                        "POST", "/api/tracks",
                        self.full_payload(source, value),
                    )
                else:
                    status, body = self.post_raw(
                        '{"title": "不应收录的候选", '
                        f'"source": "{source}", '
                        f'"duration": {value}, '
                        '"description": "不应保存的候选说明"}'
                    )
                self.assertEqual(status, 400, body)
                self.assertEqual(body["field"], "duration")
                self.assertIn("时长", body["error"])
                self.assert_library_unchanged()

    def test_valid_create_after_duration_failures_extends_library(self):
        # 多次时长失败后，一次合法收录仍能成功，接在已有记录之后，
        # 失败请求不留下额外记录。
        for bad in (-1, "243.5", False):
            status, _ = self.server.request(
                "POST", "/api/tracks",
                {
                    "title": "失败候选",
                    "source": f"/music/never-written-{bad!r}.flac",
                    "duration": bad,
                    "description": "不应保存",
                },
            )
            self.assertEqual(status, 400)
        self.assert_library_unchanged()

        status, body = self.server.request("POST", "/api/tracks", {
            "title": "补收录的曲目",
            "source": "/music/after-duration-failures.flac",
            "duration": 240,
            "description": "修正后收录",
        })
        self.assertEqual(status, 201, body)
        self.assertEqual(
            [t["id"] for t in self.list_tracks()],
            self.expected_ids + [body["id"]],
        )
        self.assertEqual(self.track_by_id(body["id"]), body)
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)
        self.assertEqual(self.track_by_id(self.second["id"]), self.second)


class CreateDurationNewVersionApiTest(ServerTestCase):
    """同一来源明确另存新版本：时长规则与普通收录完全相同。"""

    def setUp(self):
        super().setUp()
        self.first = self.create_track(
            title="夜航·首版",
            source="/music/yehang.flac",
            duration=243.5,
            cover_url="https://img.example/yehang.png",
            description="首版说明",
            tags=["民谣", "现场"],
        )

    def test_valid_duration_saved_under_new_id_with_original_intact(self):
        payload = {
            "title": "夜航·重制",
            # 仅首尾空白不同仍视为同一来源，但本次明确要求另存。
            "source": " \t/music/yehang.flac\n ",
            "duration": 250,
            "cover_url": "https://img.example/yehang-remaster.png",
            "description": "重制说明",
            "tags": ["民谣", "重制"],
            "save_as_new_version": True,
        }
        status, body = self.server.request("POST", "/api/tracks", payload)
        self.assertEqual(status, 201, body)
        self.assertNotEqual(body["id"], self.first["id"])
        # 合法时长随本次资料保存到新标识下。
        self.assertEqual(body, {
            "id": body["id"],
            "title": "夜航·重制",
            "source": "/music/yehang.flac",
            "duration": 250,
            "cover_url": "https://img.example/yehang-remaster.png",
            "description": "重制说明",
            "tags": ["民谣", "重制"],
        })
        tracks = self.list_tracks()
        self.assertEqual(
            [t["id"] for t in tracks], [self.first["id"], body["id"]]
        )
        # 原版本的时长与其他资料保持原样，没有被覆盖。
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)

    def test_null_duration_new_version_leaves_known_original_intact(self):
        # 新版本时长未知，原版本仍是已知时长，两者互不影响。
        status, body = self.server.request("POST", "/api/tracks", {
            "title": "夜航·现场",
            "source": "/music/yehang.flac",
            "duration": None,
            "save_as_new_version": True,
        })
        self.assertEqual(status, 201, body)
        self.assertIsNone(body["duration"])
        self.assertEqual(self.track_by_id(body["id"])["duration"], None)
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)
        self.assertEqual(
            self.track_by_id(self.first["id"])["duration"], 243.5
        )

    def assert_rejected_without_new_version(self, payload, *, raw=False):
        if raw:
            status, body = self.post_raw(payload)
        else:
            status, body = self.server.request(
                "POST", "/api/tracks", payload
            )
        self.assertEqual(status, 400, body)
        # 即使已明确同意另存，也报告时长错误。
        self.assertEqual(body["field"], "duration")
        self.assertIn("时长", body["error"])
        # 不新增版本，不覆盖旧曲目。
        tracks = self.list_tracks()
        self.assertEqual([t["id"] for t in tracks], [self.first["id"]])
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)

    def test_invalid_duration_with_flag_creates_no_new_version(self):
        for bad in (-1, "243.5", "0", False, True, [], {}):
            with self.subTest(bad=bad):
                self.assert_rejected_without_new_version({
                    "title": "夜航·失败重录",
                    "source": "/music/yehang.flac",
                    "duration": bad,
                    "cover_url": "https://img.example/new.png",
                    "description": "不应保存的重录说明",
                    "tags": ["重录"],
                    "save_as_new_version": True,
                })

    def test_non_finite_duration_with_flag_creates_no_new_version(self):
        for raw_fragment in ("NaN", "Infinity", "-Infinity", "1e999"):
            with self.subTest(raw=raw_fragment):
                self.assert_rejected_without_new_version(
                    '{"title": "夜航·失败重录", '
                    '"source": "/music/yehang.flac", '
                    f'"duration": {raw_fragment}, '
                    '"description": "不应保存的重录说明", '
                    '"save_as_new_version": true}',
                    raw=True,
                )


class HomeCreateRequiredFieldEmptyLibraryTest(ServerTestCase):
    """空曲库时首页收录表单必填失败：400 回填，仍显示没有记录。"""

    def assert_error_for_field(self, page, field, label):
        # 顶部失败提示。
        banner = BANNER_ERROR_RE.search(page)
        self.assertIsNotNone(banner, "页面应显示失败提示")
        self.assertIn(label, strip_tags(banner.group(1)))
        # 对应字段附近指出错误。
        field_errors = [strip_tags(raw) for raw in FIELD_ERROR_RE.findall(page)]
        self.assertTrue(
            any(label in text for text in field_errors),
            f"{label}字段附近应显示错误，实际：{field_errors}",
        )

    def assert_still_empty_library(self, page):
        # 记录数量不增加；空曲库仍显示没有记录，而不是出现列表。
        self.assertEqual(self.list_tracks(), [])
        self.assertIsNone(TRACK_LIST_RE.search(page))
        self.assertIn("还没有曲目记录", page)

    def test_blank_title_or_source_returns_400_and_reprints(self):
        for field, label, typed in (
            ("title", "名称", ""),
            ("title", "名称", "   "),
            ("title", "名称", "\t\n "),
            ("source", "来源", ""),
            ("source", "来源", "  \t"),
        ):
            with self.subTest(field=field, typed=repr(typed)):
                status, _, page = self.post_create_form(
                    self.create_form_fields(
                        title=typed if field == "title" else "山涧晨曲",
                        source=typed if field == "source" else "/音乐/现场.flac",
                    )
                )
                self.assertEqual(status, 400, page[:500])
                self.assert_error_for_field(page, field, label)
                self.assert_still_empty_library(page)

    def test_failed_submission_reprints_every_filled_field(self):
        # 名称只填空白导致失败；来源、时长、封面、说明、标签与另存选择
        # 都必须按本次填写回填，不能用任何已有记录的资料替换（此时也
        # 根本没有已有记录）。
        description = "中文说明\n第二行 <img src=x> 看起来像标签\n结尾"
        fields = self.create_form_fields(
            title=" \t ",
            source="/音乐/现场 录音/夜航.flac",
            duration="243.5",
            cover_url="https://img.example/cover.png",
            description=description,
            tags="民谣,现场，新编、自留",
            save_as_new_version=True,
        )
        status, _, page = self.post_create_form(fields)
        self.assertEqual(status, 400)
        self.assert_error_for_field(page, "title", "名称")

        self.assert_form_values(
            page,
            title=" \t ",
            source="/音乐/现场 录音/夜航.flac",
            duration="243.5",
            cover_url="https://img.example/cover.png",
            description=description,
        )
        self.assertEqual(
            parse_input_value(page, "tags", "tags"), "民谣,现场，新编、自留"
        )
        # 另存选择保留为勾选。
        checkbox = FORCE_CHECKBOX_RE.search(page)
        self.assertIsNotNone(checkbox)
        self.assertIn("checked", checkbox.group(0))
        self.assert_still_empty_library(page)

    def test_failed_submission_without_checkbox_keeps_it_unchecked(self):
        # 来源空白导致失败且未勾选另存：回填页不得偷偷选中勾选框。
        fields = self.create_form_fields(
            title="山涧晨曲",
            source="   ",
            duration="12",
            description="说明",
            tags="标签",
            save_as_new_version=False,
        )
        status, _, page = self.post_create_form(fields)
        self.assertEqual(status, 400)
        self.assert_error_for_field(page, "source", "来源")
        checkbox = FORCE_CHECKBOX_RE.search(page)
        self.assertIsNotNone(checkbox)
        self.assertNotIn("checked", checkbox.group(0))
        # 来源框回填本次填写的空白。
        self.assert_form_values(page, source="   ", title="山涧晨曲")
        self.assert_still_empty_library(page)

    def test_description_html_looking_text_is_escaped_in_reprint(self):
        # 说明中的中文、换行与看起来像网页标签的内容在回填时按普通文字
        # 转义显示，不会变成页面元素；框内呈现仍是原文。
        description = (
            "中文“引号”\n<尖括号> 与 <b>看起来像标签</b>\n"
            "</textarea><script>alert(1)</script>"
        )
        fields = self.create_form_fields(
            title="", source="/music/desc.flac", description=description,
        )
        status, _, page = self.post_create_form(fields)
        self.assertEqual(status, 400)
        self.assertEqual(parse_description_box(page), description)
        markup = description_box_markup(page)
        self.assertNotIn("<script>", markup)
        self.assertNotIn("<b>", markup)
        self.assertIn("&lt;b&gt;", markup)
        self.assertIn("&lt;/textarea&gt;", markup)


class HomeCreateRequiredFieldWithExistingTest(ServerTestCase):
    """已有曲目时首页必填失败：已有记录完整保留；修正后新增完整曲目。"""

    def setUp(self):
        super().setUp()
        self.first = self.create_track(
            title="已有曲目·甲",
            source="/music/existing-a.flac",
            duration=12,
            cover_url="https://img.example/a.png",
            description="甲的说明\n第二行",
            tags=["民谣"],
        )
        self.second = self.create_track(
            title="已有曲目·乙", source="/music/existing-b.flac",
        )
        self.expected_ids = [self.first["id"], self.second["id"]]

    def assert_library_unchanged(self):
        tracks = self.list_tracks()
        self.assertEqual([t["id"] for t in tracks], self.expected_ids)
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)
        self.assertEqual(self.track_by_id(self.second["id"]), self.second)

    def assert_field_error(self, page, label):
        banner = BANNER_ERROR_RE.search(page)
        self.assertIsNotNone(banner)
        self.assertIn(label, strip_tags(banner.group(1)))
        field_errors = [strip_tags(raw) for raw in FIELD_ERROR_RE.findall(page)]
        self.assertTrue(any(label in text for text in field_errors))

    def test_blank_required_fields_keep_existing_records_intact(self):
        for field, typed in (
            ("title", ""), ("title", "  \t "),
            ("source", ""), ("source", "\n\t"),
        ):
            with self.subTest(field=field, typed=repr(typed)):
                status, _, page = self.post_create_form(
                    self.create_form_fields(
                        title=typed if field == "title" else "候选名称",
                        source=typed if field == "source"
                        else "/音乐/新来源.flac",
                        duration="307.25",
                        cover_url="https://img.example/new.png",
                        description="候选说明\n换行",
                        tags="候选,新编",
                    )
                )
                self.assertEqual(status, 400, page[:500])
                self.assert_field_error(page, "名称" if field == "title" else "来源")
                # 已有曲目完整资料与列表顺序不变，数量不增加。
                self.assert_library_unchanged()
                # 列表区仍只列出提交前的两条已有记录。
                self.assertEqual(
                    parse_listed_tracks(page),
                    [(self.first["id"], "已有曲目·甲"),
                     (self.second["id"], "已有曲目·乙")],
                )

    def test_reprint_uses_submission_not_existing_record_data(self):
        # 失败回填必须保留本次填写，不能用已有记录（甲）的资料替换：
        # 名称、来源、时长、封面、说明、标签、另存选择都与甲不同。
        description = "本次填写：中文\n<img src=x> 不是标签\n  结尾两空格"
        fields = self.create_form_fields(
            title="",  # 名称留空导致失败
            source="/音乐/候选/录音.flac",
            duration="307.25",
            cover_url="https://img.example/candidate.png",
            description=description,
            tags="候选,新编",
            save_as_new_version=True,
        )
        status, _, page = self.post_create_form(fields)
        self.assertEqual(status, 400)
        self.assert_field_error(page, "名称")

        self.assert_form_values(
            page,
            title="",
            source="/音乐/候选/录音.flac",
            duration="307.25",
            cover_url="https://img.example/candidate.png",
            description=description,
        )
        self.assertEqual(parse_input_value(page, "tags", "tags"), "候选,新编")
        checkbox = FORCE_CHECKBOX_RE.search(page)
        self.assertIn("checked", checkbox.group(0))
        self.assert_library_unchanged()
        # 回填说明里看起来像标签的文字被转义，按普通文字显示。
        self.assertIn("&lt;img src=x&gt;", description_box_markup(page))

    def test_fix_only_bad_title_saves_complete_new_record(self):
        # 第一次：名称空白导致失败，其余资料（含另存勾选）完整填写。
        description = "失败前填写的说明：中文\n第二行换行\n"
        failed_fields = self.create_form_fields(
            title="   ",
            source="/音乐/修正后保存.flac",
            duration="307.25",
            cover_url="https://img.example/candidate.png",
            description=description,
            tags="候选,新编,候选",
            save_as_new_version=True,
        )
        status, _, failed_page = self.post_create_form(failed_fields)
        self.assertEqual(status, 400)
        self.assert_library_unchanged()

        # 用户只修正出错的名称，保留错误页中的其他全部填写（含勾选）再保存。
        retry_fields = self.create_fields_from_rendered_page(failed_page)
        retry_fields = [
            ("title", "修正后的名称") if name == "title" else (name, value)
            for name, value in retry_fields
        ]
        status, headers, _ = self.post_create_form(retry_fields)
        self.assertEqual(status, 303, headers)
        new_id = int(
            re.search(r"highlight=(\d+)$", headers["Location"]).group(1)
        )
        self.assertNotIn(new_id, self.expected_ids)

        # 新增一条采用本次完整资料的曲目：失败前填写的选填内容没丢，
        # 标签按既有规则裁剪、去重；勾选的另存选择不影响这条全新来源。
        new_record = self.track_by_id(new_id)
        self.assertEqual(new_record, {
            "id": new_id,
            "title": "修正后的名称",
            "source": "/音乐/修正后保存.flac",
            "duration": 307.25,
            "cover_url": "https://img.example/candidate.png",
            "description": description,
            "tags": ["候选", "新编"],
        })
        # 已有记录保持原样，新记录按标识顺序接在后面。
        self.assertEqual(
            [t["id"] for t in self.list_tracks()],
            self.expected_ids + [new_id],
        )
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)
        self.assertEqual(self.track_by_id(self.second["id"]), self.second)

    def test_fix_only_bad_source_then_listing_shows_saved_title_and_source(self):
        # 第一次：来源只填空白导致失败，名称与选填资料已填好。
        failed_fields = self.create_form_fields(
            title="夜航·现场收录",
            source=" \t\n ",
            duration="8",
            description="现场版本说明",
            tags="现场",
        )
        status, _, failed_page = self.post_create_form(failed_fields)
        self.assertEqual(status, 400)
        self.assert_field_error(failed_page, "来源")
        self.assert_library_unchanged()

        # 只把来源修正为尚未收录的文字，其余内容直接取错误页的回填
        # （名称、时长、说明、标签都保留失败前的填写）再提交。
        retry_fields = self.create_fields_from_rendered_page(failed_page)
        retry_fields = [
            ("source", "/音乐/夜航/现场.flac") if name == "source"
            else (name, value)
            for name, value in retry_fields
        ]
        status, headers, _ = self.post_create_form(retry_fields)
        self.assertEqual(status, 303, headers)
        new_id = int(
            re.search(r"highlight=(\d+)$", headers["Location"]).group(1)
        )

        # 成功提交后回到列表，显示刚保存的名称与来源。
        status, _, listing_page = self.server.get_page(headers["Location"])
        self.assertEqual(status, 200)
        self.assertIn("夜航·现场收录", listing_page)
        self.assertIn("/音乐/夜航/现场.flac", listing_page)
        new_record = self.track_by_id(new_id)
        self.assertEqual(new_record["title"], "夜航·现场收录")
        self.assertEqual(new_record["source"], "/音乐/夜航/现场.flac")
        self.assertEqual(new_record["duration"], 8)
        self.assertEqual(new_record["tags"], ["现场"])
        self.assertEqual(
            [t["id"] for t in self.list_tracks()],
            self.expected_ids + [new_id],
        )

    def test_successful_create_with_chinese_fields_shown_on_listing(self):
        # 首页成功提交（中文名称、含中文路径的来源、首尾空白）后回到列表，
        # 显示刚保存的名称与来源，首尾空白已去掉。
        fields = self.create_form_fields(
            title="  夜航·序曲  ",
            source="\t/音乐/现场/序曲.flac\n",
        )
        status, headers, _ = self.post_create_form(fields)
        self.assertEqual(status, 303, headers)
        new_id = int(
            re.search(r"highlight=(\d+)$", headers["Location"]).group(1)
        )
        status, _, listing_page = self.server.get_page(headers["Location"])
        self.assertEqual(status, 200)
        self.assertEqual(parse_listed_tracks(listing_page), [
            (self.first["id"], "已有曲目·甲"),
            (self.second["id"], "已有曲目·乙"),
            (new_id, "夜航·序曲"),
        ])
        self.assertIn("/音乐/现场/序曲.flac", listing_page)
        record = self.track_by_id(new_id)
        self.assertEqual(record["title"], "夜航·序曲")
        self.assertEqual(record["source"], "/音乐/现场/序曲.flac")
        # 省略选填资料的默认结果：时长未知、封面说明为空、标签为空数组。
        self.assertIsNone(record["duration"])
        self.assertEqual(record["cover_url"], "")
        self.assertEqual(record["description"], "")
        self.assertEqual(record["tags"], [])


class HomeCreateDurationValidSaveTest(ServerTestCase):
    """首页收录表单：时长填写方式决定这次保存的结果（合法路径）。

    名称、来源等其余资料合法且来源尚未收录时，非负整数与有限的非负
    小数文字保存成功：303 回首页、提示收录成功，列表新增一条采用本次
    完整资料的曲目，时长按填写的秒数保存和展示；“0”与未知严格区分。
    """

    def submit_and_open_listing(self, fields):
        status, headers, _ = self.post_create_form(fields)
        self.assertEqual(status, 303, "保存应成功并 303 回首页")
        match = re.search(r"highlight=(\d+)$", headers["Location"])
        self.assertIsNotNone(match, headers["Location"])
        new_id = int(match.group(1))
        status, _, listing_page = self.server.get_page(headers["Location"])
        self.assertEqual(status, 200, listing_page[:500])
        return new_id, listing_page

    def test_decimal_seconds_saved_and_shown_without_conversion(self):
        # 有限非负小数：不换算成分钟，不把小数截成整数。
        fields = self.create_form_fields(
            title="夜航·现场",
            source="/音乐/yehang-live.flac",
            duration="243.5",
            cover_url="https://img.example/yehang.png",
            description="现场录音\n第二行中文",
            tags="民谣,现场,民谣",
        )
        new_id, listing_page = self.submit_and_open_listing(fields)

        # 首页提示收录成功，并指出新曲目标识。
        success = strip_tags(BANNER_SUCCESS_RE.search(listing_page).group(1))
        self.assertIn("收录成功", success)
        self.assertIn(f"#{new_id}", success)
        # 列表显示新曲目，时长按填写的秒数展示为“243.5 秒”。
        self.assertEqual(parse_listed_tracks(listing_page),
                         [(new_id, "夜航·现场")])
        self.assertEqual(parse_listed_durations(listing_page), ["243.5 秒"])

        # 只新增一条采用本次完整资料的曲目：标签裁剪去重，其余原样。
        tracks = self.list_tracks()
        self.assertEqual(len(tracks), 1)
        record = tracks[0]
        self.assertEqual(record, {
            "id": new_id,
            "title": "夜航·现场",
            "source": "/音乐/yehang-live.flac",
            "duration": 243.5,
            "cover_url": "https://img.example/yehang.png",
            "description": "现场录音\n第二行中文",
            "tags": ["民谣", "现场"],
        })
        # 随后从曲目列表接口读到的时长与网页显示一致（不截断小数）。
        self.assertIsInstance(record["duration"], float)
        self.assertEqual(self.track_by_id(new_id)["duration"], 243.5)

    def test_integer_seconds_kept_as_integer_seconds(self):
        fields = self.create_form_fields(
            title="整数秒曲目", source="/music/seconds.flac", duration="307",
        )
        new_id, listing_page = self.submit_and_open_listing(fields)
        self.assertEqual(parse_listed_tracks(listing_page),
                         [(new_id, "整数秒曲目")])
        self.assertEqual(parse_listed_durations(listing_page), ["307 秒"])
        record = self.track_by_id(new_id)
        self.assertEqual(record["duration"], 307)
        self.assertIsInstance(record["duration"], int)

    def test_zero_is_zero_seconds_not_unknown(self):
        # 特别保留零与未知的区别：填写“0”后显示“0 秒”，零仍是数字零。
        fields = self.create_form_fields(
            title="零秒曲目", source="/music/zero.flac", duration="0",
        )
        new_id, listing_page = self.submit_and_open_listing(fields)
        self.assertEqual(parse_listed_durations(listing_page), ["0 秒"])
        record = self.track_by_id(new_id)
        self.assertEqual(record["duration"], 0)
        self.assertIsNotNone(record["duration"])
        self.assertIsInstance(record["duration"], int)

    def test_empty_and_whitespace_box_save_as_unknown(self):
        # 时长框留空或只填空白则保存为未知：列表显示“未知”，接口为 null。
        for typed in ("", " ", "\t", "  \t "):
            with self.subTest(typed=repr(typed)):
                title = f"未知时长曲目 {typed!r}"
                new_id, listing_page = self.submit_and_open_listing(
                    self.create_form_fields(
                        title=title,
                        source=f"/music/unknown-{len(self.list_tracks())}.flac",
                        duration=typed,
                    )
                )
                self.assertEqual(parse_listed_durations(listing_page)[-1:],
                                 ["未知"])
                record = self.track_by_id(new_id)
                self.assertIsNone(record["duration"])

    def test_surrounding_whitespace_does_not_change_number(self):
        # 数字前后的空白不影响数值；保存与展示都是去掉空白后的秒数。
        fields = self.create_form_fields(
            title="带空白的数字", source="/music/spaced.flac",
            duration=" \t 243.5 \n",
        )
        new_id, listing_page = self.submit_and_open_listing(fields)
        self.assertEqual(parse_listed_durations(listing_page), ["243.5 秒"])
        self.assertEqual(self.track_by_id(new_id)["duration"], 243.5)

    def test_extra_decimal_forms_accepted(self):
        # .5 / +12 / 0.0 都是有限非负数字文字，按对应数值保存。
        for typed, expected in ((".5", 0.5), ("+12", 12.0), ("0.0", 0)):
            with self.subTest(typed=typed):
                new_id, _ = self.submit_and_open_listing(
                    self.create_form_fields(
                        title=f"形式 {typed}",
                        source=f"/music/form-{len(self.list_tracks())}.flac",
                        duration=typed,
                    )
                )
                self.assertEqual(
                    self.track_by_id(new_id)["duration"], expected
                )


class HomeCreateDurationInvalidTest(ServerTestCase):
    """首页收录表单：时长无法解析为有限非负数时 400，原样回填且不写入。"""

    def assert_duration_error_shown(self, page, typed):
        # 页面显示保存失败。
        banner = BANNER_ERROR_RE.search(page)
        self.assertIsNotNone(banner, "页面应显示保存失败提示")
        self.assertIn("保存失败", strip_tags(banner.group(1)))
        self.assertIn("时长", strip_tags(banner.group(1)))
        # 时长字段附近明确说明时长有误。
        field_errors = [strip_tags(raw) for raw in FIELD_ERROR_RE.findall(page)]
        self.assertTrue(
            any("时长" in text for text in field_errors),
            f"时长字段附近应显示错误，实际：{field_errors}",
        )
        # 时长框必须保留本次填写的原文，不能改成空白、零或其他值。
        self.assert_form_values(page, duration=typed)

    def full_fields(self, duration, *, save_as_new_version=False):
        return self.create_form_fields(
            title="夜航·候选",
            source="/音乐/候选/录音.flac",
            duration=duration,
            cover_url="https://img.example/candidate.png",
            description="候选说明：中文\n第二行 <b>看起来像标签</b>\n结尾",
            tags="民谣,现场，新编、自留",
            save_as_new_version=save_as_new_version,
        )

    def test_bad_texts_return_400_and_keep_typed_text(self):
        for typed in ("-1", "-0.5", "-243.5", "abc", "时长",
                      "NaN", "Infinity", "-Infinity", "1e999",
                      "1e1000", "0x10", "1.2.3"):
            with self.subTest(typed=typed):
                status, _, page = self.post_create_form(
                    self.full_fields(typed)
                )
                self.assertEqual(status, 400, page[:500])
                self.assert_duration_error_shown(page, typed)

    def test_failed_submission_reprints_every_filled_field(self):
        # 时长错误时，名称、来源、封面地址、说明、标签与另存选择也保留
        # 本次填写；勾选另存为新版本时回填页仍保持勾选。
        fields = self.full_fields("abc", save_as_new_version=True)
        status, _, page = self.post_create_form(fields)
        self.assertEqual(status, 400)
        self.assert_duration_error_shown(page, "abc")
        self.assert_form_values(
            page,
            title="夜航·候选",
            source="/音乐/候选/录音.flac",
            duration="abc",
            cover_url="https://img.example/candidate.png",
            description="候选说明：中文\n第二行 <b>看起来像标签</b>\n结尾",
        )
        self.assertEqual(
            parse_input_value(page, "tags", "tags"),
            "民谣,现场，新编、自留",
        )
        checkbox = FORCE_CHECKBOX_RE.search(page)
        self.assertIsNotNone(checkbox)
        self.assertIn("checked", checkbox.group(0))

    def test_unchecked_save_as_new_version_stays_unchecked(self):
        # 未勾选另存时，时长失败的回填页不得偷偷选中勾选框。
        fields = self.full_fields("-5", save_as_new_version=False)
        status, _, page = self.post_create_form(fields)
        self.assertEqual(status, 400)
        self.assert_duration_error_shown(page, "-5")
        checkbox = FORCE_CHECKBOX_RE.search(page)
        self.assertIsNotNone(checkbox)
        self.assertNotIn("checked", checkbox.group(0))

    def test_description_chinese_newlines_tags_shown_as_plain_text(self):
        # 说明中的中文、换行与看起来像网页标签的文字仍按普通文字显示，
        # 不能在失败回填时丢掉或变成页面内容。
        description = (
            "中文“引号”\n<尖括号> 与 <b>看起来像标签</b>\n"
            "</textarea><script>alert(1)</script>"
        )
        fields = self.create_form_fields(
            title="夜航·候选",
            source="/music/candidate.flac",
            duration="1e999",
            description=description,
        )
        status, _, page = self.post_create_form(fields)
        self.assertEqual(status, 400)
        self.assertEqual(parse_description_box(page), description)
        markup = description_box_markup(page)
        self.assertNotIn("<script>", markup)
        self.assertNotIn("<b>", markup)
        self.assertIn("&lt;b&gt;", markup)
        self.assertIn("&lt;/textarea&gt;", markup)


class HomeCreateDurationInvalidEmptyLibraryTest(ServerTestCase):
    """空曲库时首页时长失败：400 回填，不新增任何记录或保存部分资料。"""

    def test_invalid_duration_creates_nothing_in_empty_library(self):
        for typed in ("-1", "abc", "NaN", "Infinity", "1e999"):
            with self.subTest(typed=typed):
                status, _, page = self.post_create_form(
                    self.create_form_fields(
                        title="不应收录的曲目",
                        source=f"/music/empty-{typed}.flac",
                        duration=typed,
                        cover_url="https://img.example/x.png",
                        description="不应保存的说明",
                        tags="不应保存的标签",
                    )
                )
                self.assertEqual(status, 400)
                # 不新增任何曲目：接口为空，页面仍显示没有记录。
                self.assertEqual(self.list_tracks(), [])
                self.assertIsNone(TRACK_LIST_RE.search(page))
                self.assertIn("还没有曲目记录", page)
                # 时长框保留原文，便于直接修正。
                self.assert_form_values(page, duration=typed)


class HomeCreateDurationInvalidWithExistingTest(ServerTestCase):
    """已有曲目时首页时长失败：已有记录完整资料、数量与顺序保持原样。"""

    def setUp(self):
        super().setUp()
        self.first = self.create_track(
            title="已有曲目·甲",
            source="/music/existing-a.flac",
            duration=12,
            cover_url="https://img.example/a.png",
            description="甲的说明\n第二行",
            tags=["民谣"],
        )
        self.second = self.create_track(
            title="已有曲目·乙", source="/music/existing-b.flac",
            duration=33.3, tags=["现场"],
        )
        self.existing_ids = [self.first["id"], self.second["id"]]

    def assert_library_unchanged(self, page):
        tracks = self.list_tracks()
        # 数量不增加，列表顺序保持原样。
        self.assertEqual([t["id"] for t in tracks], self.existing_ids)
        # 已有曲目的完整资料一条都没被改写。
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)
        self.assertEqual(self.track_by_id(self.second["id"]), self.second)
        # 失败页列表区仍只列出提交前的两条已有记录。
        self.assertEqual(
            parse_listed_tracks(page),
            [(self.first["id"], "已有曲目·甲"),
             (self.second["id"], "已有曲目·乙")],
        )

    def test_invalid_duration_saves_nothing_even_with_valid_metadata(self):
        for typed in ("-1", "-0.5", "普通文字", "NaN", "Infinity",
                      "-Infinity", "1e999", "1e1000"):
            with self.subTest(typed=typed):
                status, _, page = self.post_create_form(
                    self.create_form_fields(
                        title="不应收录的候选",
                        source=f"/音乐/候选-{len(typed)}.flac",
                        duration=typed,
                        cover_url="https://img.example/candidate.png",
                        description="候选说明\n换行",
                        tags="候选,新编",
                    )
                )
                self.assertEqual(status, 400, page[:500])
                self.assert_form_values(page, duration=typed)
                self.assert_library_unchanged(page)


class HomeCreateDurationRetryAfterFailureTest(ServerTestCase):
    """首页时长失败后只修正时长再保存：只新增一条，资料来自回填。"""

    def setUp(self):
        super().setUp()
        self.first = self.create_track(
            title="已有曲目",
            source="/music/existing.flac",
            duration=9,
            cover_url="https://img.example/existing.png",
            description="已有说明",
            tags=["已有标签"],
        )

    def test_fix_only_duration_saves_one_complete_new_record(self):
        # 第一次：除时长外的资料全部合法，时长写成普通文字导致 400。
        description = "失败前填写的说明：中文\n第二行换行 <img src=x>\n"
        failed_fields = self.create_form_fields(
            title="修正后收录的曲目",
            source="/音乐/候选/录音.flac",
            duration="时长未知",
            cover_url="https://img.example/candidate.png",
            description=description,
            tags="候选,新编,候选",
            save_as_new_version=True,
        )
        status, _, failed_page = self.post_create_form(failed_fields)
        self.assertEqual(status, 400)
        # 失败提交不写入任何曲目，已有记录保持原样。
        self.assertEqual(
            [t["id"] for t in self.list_tracks()], [self.first["id"]]
        )
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)

        # 用户在错误页只修正时长，保留其余回填（含另存勾选）再次保存。
        retry_fields = self.create_fields_from_rendered_page(failed_page)
        retry_fields = [
            ("duration", "243.5") if name == "duration" else (name, value)
            for name, value in retry_fields
        ]
        status, headers, _ = self.post_create_form(retry_fields)
        self.assertEqual(status, 303, headers)
        new_id = int(
            re.search(r"highlight=(\d+)$", headers["Location"]).group(1)
        )
        self.assertNotEqual(new_id, self.first["id"])

        # 只新增一条采用回填资料与修正后时长的曲目；失败提交不留额外记录。
        tracks = self.list_tracks()
        self.assertEqual(
            [t["id"] for t in tracks], [self.first["id"], new_id]
        )
        self.assertEqual(tracks[-1], {
            "id": new_id,
            "title": "修正后收录的曲目",
            "source": "/音乐/候选/录音.flac",
            "duration": 243.5,
            "cover_url": "https://img.example/candidate.png",
            "description": description,
            "tags": ["候选", "新编"],
        })
        # 已有记录仍与提交前完全一致。
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)

        # 成功后首页显示收录成功，列表时长与接口一致。
        status, _, listing_page = self.server.get_page(headers["Location"])
        self.assertEqual(status, 200)
        success = strip_tags(BANNER_SUCCESS_RE.search(listing_page).group(1))
        self.assertIn("收录成功", success)
        self.assertIn(f"#{new_id}", success)
        self.assertEqual(
            parse_listed_durations(listing_page), ["9 秒", "243.5 秒"]
        )

    def test_fix_duration_to_zero_then_to_unknown_each_adds_one_record(self):
        # 修正为“0”：收录一条已知零秒的曲目，显示“0 秒”而非未知。
        failed_fields = self.create_form_fields(
            title="先负数后零", source="/music/fix-zero.flac",
            duration="-3", description="零秒修正",
        )
        status, _, failed_page = self.post_create_form(failed_fields)
        self.assertEqual(status, 400)
        retry_fields = self.create_fields_from_rendered_page(failed_page)
        retry_fields = [
            ("duration", "0") if name == "duration" else (name, value)
            for name, value in retry_fields
        ]
        status, headers, _ = self.post_create_form(retry_fields)
        self.assertEqual(status, 303, headers)
        zero_id = int(headers["Location"].rsplit("=", 1)[1])
        self.assertEqual(self.track_by_id(zero_id)["duration"], 0)
        status, _, listing_page = self.server.get_page(headers["Location"])
        self.assertEqual(
            parse_listed_durations(listing_page), ["9 秒", "0 秒"]
        )

        # 另一次失败后把时长框清空修正：收录一条未知时长的新曲目。
        failed_fields = self.create_form_fields(
            title="先文字后留空", source="/music/fix-unknown.flac",
            duration="abc",
        )
        status, _, failed_page = self.post_create_form(failed_fields)
        self.assertEqual(status, 400)
        retry_fields = self.create_fields_from_rendered_page(failed_page)
        retry_fields = [
            ("duration", "") if name == "duration" else (name, value)
            for name, value in retry_fields
        ]
        status, headers, _ = self.post_create_form(retry_fields)
        self.assertEqual(status, 303, headers)
        unknown_id = int(headers["Location"].rsplit("=", 1)[1])
        self.assertIsNone(self.track_by_id(unknown_id)["duration"])
        # 两次失败都没有额外记录：只有已有 + 零秒 + 未知三条。
        self.assertEqual(
            [t["id"] for t in self.list_tracks()],
            [self.first["id"], zero_id, unknown_id],
        )


class HomeCreateDurationWithSourceRulesTest(ServerTestCase):
    """时长保障与来源重复、另存为新版本的既有规则并存。"""

    def setUp(self):
        super().setUp()
        self.existing = self.create_track(
            title="夜航·首版",
            source="/music/yehang.flac",
            duration=243.5,
            tags=["民谣"],
        )

    def test_duplicate_source_with_bad_duration_still_creates_nothing(self):
        # 来源重复且未另存、时长也非法：不新增任何记录，已有版本保持原样。
        fields = self.create_form_fields(
            title="夜航·候选",
            source="/music/yehang.flac",
            duration="abc",
            tags=["候选"],
        )
        status, _, page = self.post_create_form(fields)
        # 时长字段先于来源判重被校验，返回 400（而不是 409）。
        self.assertEqual(status, 400, page[:500])
        field_errors = [strip_tags(raw) for raw in FIELD_ERROR_RE.findall(page)]
        self.assertTrue(any("时长" in text for text in field_errors))
        self.assertEqual(
            [t["id"] for t in self.list_tracks()], [self.existing["id"]]
        )
        self.assertEqual(self.track_by_id(self.existing["id"]), self.existing)

    def test_bad_duration_then_duplicate_source_then_save_new_version(self):
        # 第一次：时长非法被 400 拒绝（来源尚未走到判重），不留记录。
        fields = self.create_form_fields(
            title="夜航·重录",
            source="/music/yehang.flac",
            duration="NaN",
            description="重录说明",
            tags=["重录"],
        )
        status, _, failed_page = self.post_create_form(fields)
        self.assertEqual(status, 400)
        self.assertEqual(
            [t["id"] for t in self.list_tracks()], [self.existing["id"]]
        )

        # 修正时长但仍未勾选另存：来源重复规则依旧生效，返回 409。
        retry_fields = self.create_fields_from_rendered_page(failed_page)
        retry_fields = [
            ("duration", "307.25") if name == "duration" else (name, value)
            for name, value in retry_fields
        ]
        status, _, conflict_page = self.post_create_form(retry_fields)
        self.assertEqual(status, 409, conflict_page[:500])
        self.assertEqual(
            parse_conflict_items(conflict_page),
            [(self.existing["id"], "夜航·首版")],
        )
        # 冲突拒绝同样不写入，且回填保留修正后的时长与其他本次资料。
        self.assertEqual(
            [t["id"] for t in self.list_tracks()], [self.existing["id"]]
        )
        self.assert_form_values(
            conflict_page,
            title="夜航·重录",
            source="/music/yehang.flac",
            duration="307.25",
            description="重录说明",
        )

        # 在冲突页勾选“另存为新版本”再保存：新增一条独立标识的版本，
        # 资料来自回填，时长为修正后的值；原版本不被修改。
        final_fields = self.create_fields_from_rendered_page(conflict_page)
        final_fields.append(("save_as_new_version", "1"))
        status, headers, _ = self.post_create_form(final_fields)
        self.assertEqual(status, 303, headers)
        new_id = int(headers["Location"].rsplit("=", 1)[1])
        self.assertNotEqual(new_id, self.existing["id"])
        new_record = self.track_by_id(new_id)
        self.assertEqual(new_record, {
            "id": new_id,
            "title": "夜航·重录",
            "source": "/music/yehang.flac",
            "duration": 307.25,
            "cover_url": "",
            "description": "重录说明",
            "tags": ["重录"],
        })
        self.assertEqual(
            [t["id"] for t in self.list_tracks()],
            [self.existing["id"], new_id],
        )
        self.assertEqual(self.track_by_id(self.existing["id"]), self.existing)


class EditTagsReplaceTest(ServerTestCase):
    """PATCH tags：本次提交的标签整体替换原标签，不追加、不新增记录。"""

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="夜航",
            source="/music/yehang.flac",
            duration=243.5,
            cover_url="https://img.example/yehang.png",
            description="首版说明\n第二行",
            tags=["民谣", "现场"],
        )
        self.track_id = self.track["id"]
        self.bystander = self.create_track(
            title="无关曲目", source="/music/other.flac", tags=["其他"],
        )

    def assert_rest_of_library_unchanged(self):
        tracks = self.list_tracks()
        # 修改的是原有记录：标识不变、不新增曲目，列表顺序不变。
        self.assertEqual(
            [t["id"] for t in tracks],
            [self.track_id, self.bystander["id"]],
        )
        self.assertEqual(self.track_by_id(self.bystander["id"]), self.bystander)

    def test_submitted_tags_replace_old_tags(self):
        status, body = self.patch(self.track_id, {"tags": ["摇滚", "现场版"]})
        self.assertEqual(status, 200, body)
        # 成功返回修改后的完整曲目；旧标签被替换，不追加在新标签后面。
        self.assertEqual(body, {
            "id": self.track_id,
            "title": "夜航",
            "source": "/music/yehang.flac",
            "duration": 243.5,
            "cover_url": "https://img.example/yehang.png",
            "description": "首版说明\n第二行",
            "tags": ["摇滚", "现场版"],
        })
        # 随后读取曲目列表得到相同的标签文字与顺序。
        listed = self.track_by_id(self.track_id)
        self.assertEqual(listed, body)
        self.assertEqual(listed["tags"], ["摇滚", "现场版"])
        self.assertNotIn("民谣", listed["tags"])
        self.assert_rest_of_library_unchanged()

    def test_replacement_keeps_same_id_and_record_count(self):
        before_ids = [t["id"] for t in self.list_tracks()]
        status, body = self.patch(self.track_id, {"tags": ["唯一标签"]})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["id"], self.track_id)
        self.assertEqual([t["id"] for t in self.list_tracks()], before_ids)
        self.assert_rest_of_library_unchanged()

    def test_only_tags_submitted_keeps_other_fields(self):
        status, body = self.patch(self.track_id, {"tags": ["新", "标签"]})
        self.assertEqual(status, 200, body)
        # 只提交标签时，名称、来源、时长、封面和说明保持原样。
        self.assertEqual(body, {
            "id": self.track_id,
            "title": "夜航",
            "source": "/music/yehang.flac",
            "duration": 243.5,
            "cover_url": "https://img.example/yehang.png",
            "description": "首版说明\n第二行",
            "tags": ["新", "标签"],
        })
        self.assertEqual(self.track_by_id(self.track_id), body)
        self.assert_rest_of_library_unchanged()


class EditTagsNormalizationTest(ServerTestCase):
    """PATCH tags 的逐项规整：完整文字去重，项内文字原样保留不拆分。"""

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="待规整", source="/music/clean.flac", tags=["旧标签"],
        )
        self.track_id = self.track["id"]

    def assert_tags_saved(self, submitted, expected):
        status, body = self.patch(self.track_id, {"tags": submitted})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["tags"], expected)
        # 随后读取列表，标签文字与顺序和成功响应一致。
        self.assertEqual(self.track_by_id(self.track_id)["tags"], expected)

    def test_trim_ignore_empty_and_dedup_by_full_text(self):
        # 各项去掉首尾空白、忽略空项；只有完整文字相同才去重，
        # 保留第一次出现的先后位置。
        self.assert_tags_saved(
            ["  民谣  ", "", "   ", "\n", "民谣", "现场", " 现场 ", "民谣"],
            ["民谣", "现场"],
        )

    def test_punctuation_is_tag_text_not_separator(self):
        # 中英文逗号和顿号属于标签文字，不能拆成多个标签。
        tags = ["民谣，现场", "摇滚、独立", "a,b", "中文，逗号、顿号,都保留"]
        self.assert_tags_saved(tags, tags)

    def test_chinese_and_blank_lines_inside_tag_are_kept(self):
        # 中文与项内空行原样保存，一个多行标签仍是一项。
        tags = ["第一段\n\n第三段", "中文标签"]
        self.assert_tags_saved(tags, tags)

    def test_multiline_tag_and_single_line_of_it_are_two_items(self):
        # 一个多行标签与只写其中一行的另一个标签仍是两项。
        tags = ["第一行\n第二行", "第二行"]
        self.assert_tags_saved(tags, tags)

    def test_lf_and_crlf_variants_are_not_merged(self):
        # 仅内部换行写法不同（LF 与 CRLF）的两项不能被合并，
        # 保存后各自保留提交的换行写法。
        tags = ["甲\n乙", "甲\r\n乙"]
        self.assert_tags_saved(tags, tags)


class EditTagsOmitAndClearTest(ServerTestCase):
    """未提交 tags 保留原标签；明确提交空数组或 null 则清空标签。"""

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="夜航",
            source="/music/yehang.flac",
            duration=243.5,
            cover_url="https://img.example/yehang.png",
            description="首版说明",
            tags=["民谣", "现场"],
        )
        self.track_id = self.track["id"]

    def test_omitting_tags_keeps_content_and_order(self):
        # 只修改名称或说明、没有提交 tags 时，原标签内容与顺序不变。
        status, body = self.patch(self.track_id, {
            "title": "夜航（改名）",
            "description": "新说明",
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["tags"], ["民谣", "现场"])
        self.assertEqual(
            self.track_by_id(self.track_id)["tags"], ["民谣", "现场"]
        )

    def test_empty_array_clears_tags(self):
        status, body = self.patch(self.track_id, {"tags": []})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["tags"], [])
        self.assertEqual(self.track_by_id(self.track_id)["tags"], [])

    def test_null_clears_tags(self):
        status, body = self.patch(self.track_id, {"tags": None})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["tags"], [])
        self.assertEqual(self.track_by_id(self.track_id)["tags"], [])

    def test_clearing_is_not_treated_as_unmodified(self):
        # 清空不能当作未修改：清空后原标签不再出现；
        # 之后再只改名称，标签仍是空数组，不会回到旧标签。
        status, body = self.patch(self.track_id, {"tags": []})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["tags"], [])

        status, body = self.patch(self.track_id, {"title": "夜航（改名）"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["tags"], [])
        self.assertEqual(self.track_by_id(self.track_id)["tags"], [])


class EditTagsSameSourceVersionsTest(ServerTestCase):
    """同一来源已有多个独立版本：编辑其中一条的标签不影响其他版本。"""

    def setUp(self):
        super().setUp()
        self.first = self.create_track(
            title="夜航·首版",
            source="/music/yehang.flac",
            duration=243.5,
            description="首版说明",
            tags=["民谣", "现场"],
        )
        self.second = self.create_track(
            title="夜航·重制",
            source="/music/yehang.flac",
            duration=250,
            description="重制说明",
            tags=["民谣", "重制"],
            save_as_new_version=True,
        )

    def test_editing_one_versions_tags_succeeds_without_conflict(self):
        # 来源未改动，不能触发重复来源冲突。
        status, body = self.patch(self.second["id"], {"tags": ["重制", "2026"]})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["id"], self.second["id"])
        self.assertEqual(body["source"], "/music/yehang.flac")
        self.assertEqual(body["tags"], ["重制", "2026"])

        tracks = self.list_tracks()
        # 记录数量与列表顺序不变，仍是各自独立的两条。
        self.assertEqual(
            [t["id"] for t in tracks], [self.first["id"], self.second["id"]]
        )
        self.assertEqual(self.track_by_id(self.second["id"]), body)
        # 其他版本的标签与资料不受影响。
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)


class EditTagsInvalidTest(ServerTestCase):
    """PATCH 提交非法标签：400 且 field=tags，整单失败不保存部分内容。"""

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="夜航",
            source="/music/yehang.flac",
            duration=243.5,
            cover_url="https://img.example/yehang.png",
            description="首版说明",
            tags=["民谣", "现场"],
        )
        self.track_id = self.track["id"]
        self.bystander = self.create_track(
            title="无关曲目", source="/music/other.flac", tags=["其他"],
        )

    def assert_tags_rejected(self, bad_tags):
        """非法标签（连同合法的新名称、新说明一起提交）必须整单失败。"""
        status, body = self.patch(self.track_id, {
            "title": "不应保存的新名称",
            "description": "不应保存的新说明",
            "tags": bad_tags,
        })
        self.assertEqual(status, 400, body)
        # field 指向 tags，错误文字说明标签有误。
        self.assertEqual(body["field"], "tags")
        self.assertIn("标签", body["error"])

    def assert_everything_unchanged(self):
        tracks = self.list_tracks()
        # 记录数量与列表顺序不变。
        self.assertEqual(
            [t["id"] for t in tracks],
            [self.track_id, self.bystander["id"]],
        )
        # 目标曲目的完整资料仍与提交前一致：同次请求里合法的新名称、
        # 新说明没有先写入；其他曲目也不受影响。
        self.assertEqual(self.track_by_id(self.track_id), self.track)
        self.assertEqual(self.track_by_id(self.bystander["id"]), self.bystander)

    def test_tags_as_non_array_is_rejected(self):
        for bad in ("民谣", "民谣,现场", "", {"0": "民谣"}, 5, True):
            with self.subTest(bad=bad):
                self.assert_tags_rejected(bad)
                self.assert_everything_unchanged()

    def test_non_string_items_are_rejected(self):
        for bad in (
            [1], [0.5], [True], [False], [["民谣"]], [{"tag": "民谣"}],
        ):
            with self.subTest(bad=bad):
                self.assert_tags_rejected(bad)
                self.assert_everything_unchanged()

    def test_valid_items_before_bad_item_do_not_save_partially(self):
        # 即使错误项前面已有合法标签，也不能保存部分内容。
        self.assert_tags_rejected(["合法新标签", 2, "另一个合法标签"])
        self.assert_everything_unchanged()

    def test_null_item_is_rejected_while_whole_null_clears(self):
        # 整个 tags 为 null 与数组中的 null 要区别对待：
        # 数组里的 null 是非法项，整个 tags 为 null 是清空。
        self.assert_tags_rejected([None])
        self.assert_everything_unchanged()

        status, body = self.patch(self.track_id, {"tags": None})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["tags"], [])
        self.assertEqual(self.track_by_id(self.track_id)["tags"], [])


class EditDescriptionApiOnlyFieldTest(ServerTestCase):
    """PATCH 只提交 description：更新原记录，200 与完整资料，列表一致。"""

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="夜航",
            source="/music/yehang.flac",
            duration=243.5,
            cover_url="https://img.example/yehang.png",
            description="旧说明",
            tags=["民谣", "现场"],
        )
        self.track_id = self.track["id"]

    def test_description_only_returns_200_with_full_record(self):
        new_description = "新的说明\n第二行：鸟鸣"
        status, body = self.patch(self.track_id, {"description": new_description})
        self.assertEqual(status, 200, body)
        # 成功响应是修改后的完整曲目，曲目标识保持不变。
        self.assertEqual(body, {
            "id": self.track_id,
            "title": "夜航",
            "source": "/music/yehang.flac",
            "duration": 243.5,
            "cover_url": "https://img.example/yehang.png",
            "description": new_description,
            "tags": ["民谣", "现场"],
        })

    def test_listed_description_matches_success_response(self):
        new_description = "定稿说明"
        status, body = self.patch(self.track_id, {"description": new_description})
        self.assertEqual(status, 200, body)
        # 随后从曲目列表接口读到的说明与完整记录都与成功响应一致。
        self.assertEqual(self.track_by_id(self.track_id), body)
        self.assertEqual(
            self.track_by_id(self.track_id)["description"], new_description
        )

    def test_only_description_changes_other_fields_keep_values(self):
        status, body = self.patch(self.track_id, {"description": "只改说明"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["id"], self.track_id)
        # 名称、来源、时长、封面和标签继续保留原值。
        self.assertEqual(body["title"], self.track["title"])
        self.assertEqual(body["source"], self.track["source"])
        self.assertEqual(body["duration"], self.track["duration"])
        self.assertEqual(body["cover_url"], self.track["cover_url"])
        self.assertEqual(body["tags"], self.track["tags"])
        self.assertEqual(self.track_by_id(self.track_id), body)

    def test_record_count_and_list_order_unchanged(self):
        bystander = self.create_track(
            title="无关曲目", source="/music/other.flac",
        )
        before_ids = [t["id"] for t in self.list_tracks()]
        status, body = self.patch(self.track_id, {"description": "改了说明"})
        self.assertEqual(status, 200, body)
        # 记录数量与列表顺序不变，只是原标识的资料被更新。
        self.assertEqual([t["id"] for t in self.list_tracks()], before_ids)
        self.assertEqual(
            [t["id"] for t in self.list_tracks()],
            [self.track_id, bystander["id"]],
        )


class EditDescriptionApiVerbatimTest(ServerTestCase):
    """PATCH description 按提交原文保存：不裁剪、不拆分、不替换。"""

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="原文保留", source="/music/verbatim.flac",
            description="旧说明",
        )
        self.track_id = self.track["id"]

    def assert_description_saved_verbatim(self, description):
        status, body = self.patch(self.track_id, {"description": description})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["id"], self.track_id)
        # 成功响应中的说明与提交原文逐字一致。
        self.assertEqual(
            body["description"], description,
            "成功响应的说明与提交原文不一致：\n  实际=%r\n  提交=%r"
            % (body["description"], description),
        )
        # 列表接口读到的说明同样逐字一致。
        listed = self.track_by_id(self.track_id)["description"]
        self.assertEqual(
            listed, description,
            "列表读到的说明与提交原文不一致：\n  实际=%r\n  提交=%r"
            % (listed, description),
        )

    def test_chinese_quotes_and_angle_brackets_kept(self):
        # 中文、中英文引号、尖括号都属于说明文字。
        self.assert_description_saved_verbatim(
            "中文说明：它叫“夜航”，又名 \"Night Voyage\"。"
        )

    def test_html_looking_text_kept_as_plain_text(self):
        # 看起来像网页标签的文字不能被解析、剥离或替换。
        self.assert_description_saved_verbatim(
            "段落一\n<script>alert('x')</script>\n"
            "<img src=x onerror=alert(1)>\n<div class=\"note\">保留</div>"
        )

    def test_consecutive_blank_lines_between_paragraphs_kept(self):
        # 段落之间的连续空行（多个 LF）不能被折叠成一个。
        self.assert_description_saved_verbatim("第一段\n\n\n\n第四段")

    def test_leading_and_trailing_spaces_kept(self):
        # 首尾空格属于内容，不能裁剪。
        self.assert_description_saved_verbatim("   开头三个空格与结尾两个空格  ")

    def test_leading_and_trailing_newlines_and_spaces_kept(self):
        # 开头/结尾空行与首尾空格的组合也逐字保留。
        self.assert_description_saved_verbatim("\n\n开头空两行\n结尾空两行\n\n  ")

    def test_tabs_and_blank_lines_kept(self):
        # 制表符与只含空白的行都属于内容。
        self.assert_description_saved_verbatim("\t制表开头\n  \n\t\n行尾\t")

    def test_lf_newlines_preserved_verbatim(self):
        # 直接接口提交的 LF 换行原样保留，不做任何统一。
        description = "第一行\n第二行\n\n第四行"
        self.assert_description_saved_verbatim(description)
        self.assertNotIn("\r", self.track_by_id(self.track_id)["description"])

    def test_crlf_newlines_preserved_verbatim(self):
        # 直接接口提交的 CRLF 换行原样保留，不能套用网页表单的 LF 归一化。
        description = "第一行\r\n第二行\r\n\r\n第四行"
        self.assert_description_saved_verbatim(description)
        self.assertIn("\r\n", self.track_by_id(self.track_id)["description"])

    def test_cr_newlines_preserved_verbatim(self):
        # 直接接口提交的旧式 CR 换行也原样保留。
        description = "第一行\r第二行\r\r第四行"
        self.assert_description_saved_verbatim(description)
        saved = self.track_by_id(self.track_id)["description"]
        self.assertIn("\r", saved)
        self.assertNotIn("\n", saved)

    def test_mixed_newline_styles_each_preserved(self):
        # 同一段文字里混用 LF、CRLF、CR 时，三种写法各自保留。
        description = "LF\n下一行\r\n再一行\rCR 行\n收尾"
        self.assert_description_saved_verbatim(description)

    def test_newline_only_variants_are_distinct(self):
        # 仅换行写法不同的两段说明是不同的提交结果，不会被统一成同一段。
        lf_text = "甲\n乙"
        crlf_text = "甲\r\n乙"
        status, body = self.patch(self.track_id, {"description": lf_text})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["description"], lf_text)
        status, body = self.patch(self.track_id, {"description": crlf_text})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["description"], crlf_text)
        self.assertNotEqual(
            self.track_by_id(self.track_id)["description"], lf_text
        )

    def test_replacing_text_with_identical_text_keeps_bytes(self):
        # 直接接口不存在网页表单的“未改动”判定：提交什么就保存什么。
        status, body = self.patch(
            self.track_id, {"description": self.track["description"]}
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["description"], "旧说明")


class EditDescriptionApiOmitClearWhitespaceTest(ServerTestCase):
    """省略 description 保留原说明；空串/null 清空；纯空白按原文保存。

    原本有文字、原本为空、原本只有空白的说明都遵守相同规则。
    """

    def make_track(self, initial_description, *, source="/music/desc.flac"):
        return self.create_track(
            title="曲目", source=source,
            description=initial_description,
        )

    # -- 修改其他合法资料但省略 description：原说明完整保留 ---------------

    def assert_omitting_description_keeps_original(self, original):
        track = self.make_track(original)
        status, body = self.patch(track["id"], {
            "title": "新名称",
            "duration": 9,
            "tags": ["新标签"],
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["id"], track["id"])
        # 省略 description 时，无论原说明是文字、空串还是纯空白，都完整保留。
        self.assertEqual(
            body["description"], original,
            "省略说明后响应中的说明与原文不一致：\n  实际=%r\n  原文=%r"
            % (body["description"], original),
        )
        self.assertEqual(
            self.track_by_id(track["id"])["description"], original
        )
        # 同次提交的其他合法资料正常保存。
        self.assertEqual(body["title"], "新名称")
        self.assertEqual(body["duration"], 9)
        self.assertEqual(body["tags"], ["新标签"])

    def test_omitting_description_keeps_text(self):
        self.assert_omitting_description_keeps_original(
            "有内容的说明\n第二行  保留空格"
        )

    def test_omitting_description_keeps_empty_string(self):
        self.assert_omitting_description_keeps_original("")

    def test_omitting_description_keeps_whitespace_only(self):
        self.assert_omitting_description_keeps_original("  \n\t\n ")

    def test_empty_patch_body_keeps_description(self):
        track = self.make_track("不随空请求改变")
        status, body = self.patch(track["id"], {})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["description"], "不随空请求改变")
        self.assertEqual(self.track_by_id(track["id"]), track)

    # -- 明确提交空字符串：保存为空字符串 ---------------------------------

    def assert_empty_string_clears(self, original):
        track = self.make_track(original)
        status, body = self.patch(track["id"], {"description": ""})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["description"], "")
        self.assertEqual(self.track_by_id(track["id"])["description"], "")

    def test_empty_string_clears_text(self):
        self.assert_empty_string_clears("原本有文字")

    def test_empty_string_keeps_empty_string(self):
        self.assert_empty_string_clears("")

    def test_empty_string_clears_whitespace_only(self):
        self.assert_empty_string_clears(" \n\t ")

    # -- 明确提交 null：保存为空字符串 ------------------------------------

    def assert_null_clears(self, original):
        track = self.make_track(original)
        status, body = self.patch(track["id"], {"description": None})
        self.assertEqual(status, 200, body)
        # null 的含义是清空：保存为空字符串。
        self.assertEqual(body["description"], "")
        self.assertEqual(self.track_by_id(track["id"])["description"], "")

    def test_null_clears_text(self):
        self.assert_null_clears("原本有文字\n第二行")

    def test_null_keeps_empty_string(self):
        self.assert_null_clears("")

    def test_null_clears_whitespace_only(self):
        self.assert_null_clears("\n\n  \t")

    # -- 只含空白的字符串：按原文保存，不能当成空字符串 -------------------

    def assert_whitespace_saved_verbatim(self, whitespace):
        track = self.make_track("一段文字")
        status, body = self.patch(track["id"], {"description": whitespace})
        self.assertEqual(status, 200, body)
        self.assertEqual(
            body["description"], whitespace,
            "纯空白说明被改写：\n  实际=%r\n  提交=%r"
            % (body["description"], whitespace),
        )
        listed = self.track_by_id(track["id"])["description"]
        self.assertEqual(listed, whitespace)
        # 明确区别于空字符串。
        self.assertNotEqual(listed, "")
        self.assertTrue(listed)

    def test_spaces_only_saved_verbatim(self):
        self.assert_whitespace_saved_verbatim("     ")

    def test_tabs_only_saved_verbatim(self):
        self.assert_whitespace_saved_verbatim("\t\t")

    def test_blank_lines_only_saved_verbatim(self):
        self.assert_whitespace_saved_verbatim("\n\n\n")

    def test_mixed_whitespace_and_blank_lines_saved_verbatim(self):
        self.assert_whitespace_saved_verbatim("  \n\t\n \r\n ")

    def test_empty_blank_and_whitespace_states_are_not_swapped(self):
        # 空串、纯空白两种状态各自稳定：保存后再次只改名称，状态不互换。
        for index, value in enumerate(("", "   ", "\n\n", " \t \n")):
            with self.subTest(value=value):
                track = self.make_track(
                    "初始文字", source=f"/music/state-{index}.flac"
                )
                status, body = self.patch(track["id"], {"description": value})
                self.assertEqual(status, 200, body)
                status, body = self.patch(track["id"], {"title": "改个名称"})
                self.assertEqual(status, 200, body)
                self.assertEqual(
                    body["description"], value,
                    "状态被替换：\n  实际=%r\n  期望=%r"
                    % (body["description"], value),
                )
                self.assertEqual(
                    self.track_by_id(track["id"])["description"], value
                )

    def test_clearing_then_writing_text_round_trips(self):
        # 文字 -> 清空 -> 再写文字，两种操作都在同一标识上生效，
        # 响应与列表读取始终保持一致。
        track = self.make_track("最初的说明")
        status, body = self.patch(track["id"], {"description": ""})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["description"], "")
        status, body = self.patch(track["id"], {"description": "重新写的说明"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["description"], "重新写的说明")
        self.assertEqual(
            self.track_by_id(track["id"])["description"], "重新写的说明"
        )


class EditDescriptionApiSameSourceVersionsTest(ServerTestCase):
    """同一来源的多个独立版本：只改一条的说明，其他版本完整资料不变。"""

    def setUp(self):
        super().setUp()
        self.first = self.create_track(
            title="夜航·首版",
            source="/music/yehang.flac",
            duration=243.5,
            cover_url="https://img.example/yehang.png",
            description="首版说明",
            tags=["民谣", "现场"],
        )
        self.second = self.create_track(
            title="夜航·重制",
            source="/music/yehang.flac",
            duration=250,
            cover_url="https://img.example/yehang-remaster.png",
            description="重制说明",
            tags=["民谣", "重制"],
            save_as_new_version=True,
        )
        self.third = self.create_track(
            title="无关曲目", source="/music/other.flac",
            description="其他来源",
        )

    def test_edit_one_versions_description_succeeds_without_conflict(self):
        new_description = "重制版的新说明\n第二行"
        status, body = self.patch(self.second["id"], {
            "description": new_description,
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["id"], self.second["id"])
        self.assertEqual(body["source"], "/music/yehang.flac")
        self.assertEqual(body["description"], new_description)
        # 来源未改，只改说明不会触发同来源冲突。

    def test_other_versions_full_records_untouched(self):
        status, body = self.patch(self.second["id"], {
            "description": "重制版说明已更新",
        })
        self.assertEqual(status, 200, body)
        tracks = self.list_tracks()
        # 记录数量与列表顺序不变，仍是各自独立的记录。
        self.assertEqual(
            [t["id"] for t in tracks],
            [self.first["id"], self.second["id"], self.third["id"]],
        )
        # 被修改的版本与成功响应一致。
        self.assertEqual(self.track_by_id(self.second["id"]), body)
        # 同一来源的其他版本完整资料不受影响。
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)
        # 其他来源的曲目也不受影响。
        self.assertEqual(self.track_by_id(self.third["id"]), self.third)

    def test_edit_description_of_every_version_independently(self):
        # 依次修改同一来源各版本的说明，各自只影响自己的标识。
        status, body = self.patch(self.first["id"], {"description": "首版更新"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["description"], "首版更新")
        status, body = self.patch(self.second["id"], {
            "description": "重制更新\r\n保留 CRLF",
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["description"], "重制更新\r\n保留 CRLF")
        self.assertEqual(
            self.track_by_id(self.first["id"])["description"], "首版更新"
        )
        self.assertEqual(
            self.track_by_id(self.second["id"])["description"],
            "重制更新\r\n保留 CRLF",
        )
        self.assertEqual(
            self.track_by_id(self.third["id"])["description"], "其他来源"
        )

    def test_clear_one_version_description_leaves_others_intact(self):
        # 清空其中一条的说明，其他版本的说明仍完整保留。
        status, body = self.patch(self.first["id"], {"description": ""})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["description"], "")
        self.assertEqual(
            self.track_by_id(self.first["id"])["description"], ""
        )
        self.assertEqual(
            self.track_by_id(self.second["id"])["description"], "重制说明"
        )


class EditDescriptionApiInvalidTypeTest(ServerTestCase):
    """PATCH description 误传非字符串类型：400 且 field=description，整单失败。"""

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="夜航",
            source="/music/yehang.flac",
            duration=243.5,
            cover_url="https://img.example/yehang.png",
            description="原说明\n第二行",
            tags=["民谣", "现场"],
        )
        self.track_id = self.track["id"]
        self.bystander = self.create_track(
            title="无关曲目",
            source="/music/yehang.flac",
            duration=250,
            description="同一来源的另一版本",
            tags=["其他"],
            save_as_new_version=True,
        )
        self.other = self.create_track(
            title="别的来源", source="/music/other.flac",
            description="不应受影响",
        )

    def assert_description_rejected(self, payload):
        """非法 description（连同合法的新名称等资料）必须整单失败。"""
        status, body = self.patch(self.track_id, payload)
        self.assertEqual(status, 400, body)
        # field 指向 description，错误文字明确指出说明类型有误。
        self.assertEqual(body["field"], "description")
        self.assertIn("说明", body["error"])

    def assert_everything_unchanged(self):
        tracks = self.list_tracks()
        # 不新增记录、不改变列表顺序。
        self.assertEqual(
            [t["id"] for t in tracks],
            [self.track_id, self.bystander["id"], self.other["id"]],
        )
        # 目标曲目完整资料保持提交前内容：同次请求里合法的新名称等
        # 资料没有先写入，原说明仍在。
        self.assertEqual(self.track_by_id(self.track_id), self.track)
        # 同一来源的其他版本与其他来源曲目都不受影响。
        self.assertEqual(self.track_by_id(self.bystander["id"]), self.bystander)
        self.assertEqual(self.track_by_id(self.other["id"]), self.other)

    def test_number_types_are_rejected(self):
        for bad in (0, 1, 243, 243.5, -3):
            with self.subTest(bad=bad):
                self.assert_description_rejected({"description": bad})
                self.assert_everything_unchanged()

    def test_booleans_are_rejected(self):
        for bad in (True, False):
            with self.subTest(bad=bad):
                self.assert_description_rejected({"description": bad})
                self.assert_everything_unchanged()

    def test_array_and_object_are_rejected(self):
        for bad in ([], ["一段说明"], {}, {"text": "一段说明"}):
            with self.subTest(bad=bad):
                self.assert_description_rejected({"description": bad})
                self.assert_everything_unchanged()

    def test_invalid_description_with_valid_title_saves_nothing(self):
        # 即使同次请求还提交了合法的新名称与其他合法资料，也不能保存
        # 其中任何一部分。
        self.assert_description_rejected({
            "title": "不应保存的新名称",
            "description": 123,
            "duration": 300,
            "tags": ["不应保存的新标签"],
        })
        self.assert_everything_unchanged()
        # 明确核对原说明仍在，而不是部分修改后的结果。
        self.assertEqual(
            self.track_by_id(self.track_id)["description"], "原说明\n第二行"
        )

    def test_invalid_description_alone_is_rejected(self):
        # 即使请求中只有出错的 description 字段，规则也相同。
        self.assert_description_rejected({"description": ["数组"]})
        self.assert_everything_unchanged()

    def test_null_is_clear_not_type_error(self):
        # null 的清空含义不能混入类型错误：null 返回 200 并清空。
        status, body = self.patch(self.track_id, {"description": None})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["description"], "")
        self.assertEqual(self.track_by_id(self.track_id)["description"], "")

    def test_null_alongside_other_changes_clears_and_saves_others(self):
        # null 与其他合法字段一起提交时，说明清空且其他字段正常保存。
        status, body = self.patch(self.track_id, {
            "title": "夜航（清空说明版）",
            "description": None,
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["title"], "夜航（清空说明版）")
        self.assertEqual(body["description"], "")
        self.assertEqual(
            self.track_by_id(self.track_id)["description"], ""
        )

    def test_legal_request_after_type_error_saves_normally(self):
        # 类型错误被拒后，用同一标识提交合法说明可以正常保存；
        # 失败请求里的内容不会被补入。
        status, body = self.patch(self.track_id, {
            "title": "不应保存的名称",
            "description": True,
        })
        self.assertEqual(status, 400, body)
        self.assertEqual(body["field"], "description")

        status, body = self.patch(self.track_id, {"description": "修正后的说明"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["description"], "修正后的说明")
        # 名称没有被失败请求改动。
        self.assertEqual(body["title"], self.track["title"])
        self.assertEqual(self.track_by_id(self.track_id), body)

    def test_type_error_leaves_no_extra_record_on_repeated_failures(self):
        # 连续多次类型错误后，列表中仍只有提交前的记录与原说明，
        # 不出现部分修改或额外记录。
        for bad in (1, False, ["x"], {"k": "v"}):
            with self.subTest(bad=bad):
                status, body = self.patch(self.track_id, {
                    "title": "反复失败的名称",
                    "description": bad,
                })
                self.assertEqual(status, 400, body)
                self.assertEqual(body["field"], "description")
                self.assert_everything_unchanged()


class EditTitleApiOnlyFieldTest(ServerTestCase):
    """PATCH 只提交 title：更新原记录，200 与完整曲目，列表一致、顺序不变。"""

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="夜航",
            source="/music/yehang.flac",
            duration=243.5,
            cover_url="https://img.example/yehang.png",
            description="旧说明\n第二行",
            tags=["民谣", "现场"],
        )
        self.track_id = self.track["id"]
        # 一首无关曲目：改名不能影响它，也不能改变列表按标识升序的关系。
        self.bystander = self.create_track(
            title="无关曲目", source="/music/other.flac", duration=7,
        )

    def test_title_only_returns_200_with_full_record(self):
        new_title = "夜航（现场版）"
        status, body = self.patch(self.track_id, {"title": new_title})
        self.assertEqual(status, 200, body)
        # 成功响应是修改后的完整曲目，曲目标识保持不变。
        self.assertEqual(body, {
            "id": self.track_id,
            "title": new_title,
            "source": "/music/yehang.flac",
            "duration": 243.5,
            "cover_url": "https://img.example/yehang.png",
            "description": "旧说明\n第二行",
            "tags": ["民谣", "现场"],
        })

    def test_listed_title_matches_success_response(self):
        new_title = "定稿名称"
        status, body = self.patch(self.track_id, {"title": new_title})
        self.assertEqual(status, 200, body)
        # 随后从曲目列表接口读到的记录与成功响应完全一致。
        self.assertEqual(self.track_by_id(self.track_id), body)
        self.assertEqual(self.track_by_id(self.track_id)["title"], new_title)

    def test_update_keeps_same_id_and_creates_nothing(self):
        before_ids = [t["id"] for t in self.list_tracks()]
        status, body = self.patch(self.track_id, {"title": "改了名称"})
        self.assertEqual(status, 200, body)
        # 更新的仍是原来的标识。
        self.assertEqual(body["id"], self.track_id)
        tracks = self.list_tracks()
        # 不增加曲目。
        self.assertEqual(len(tracks), len(before_ids))

    def test_list_stays_id_ascending(self):
        before_ids = [t["id"] for t in self.list_tracks()]
        self.assertEqual(before_ids, [self.track_id, self.bystander["id"]])
        status, body = self.patch(self.track_id, {"title": "改了名称"})
        self.assertEqual(status, 200, body)
        # 列表按标识升序的关系不变。
        self.assertEqual(
            [t["id"] for t in self.list_tracks()],
            [self.track_id, self.bystander["id"]],
        )
        # 无关曲目不被改名波及。
        self.assertEqual(
            self.track_by_id(self.bystander["id"]), self.bystander
        )

    def test_only_title_changes_other_fields_keep_values(self):
        status, body = self.patch(self.track_id, {"title": "只改名称"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["id"], self.track_id)
        # 来源、时长、封面、说明和标签继续保留原值。
        self.assertEqual(body["source"], self.track["source"])
        self.assertEqual(body["duration"], self.track["duration"])
        self.assertEqual(body["cover_url"], self.track["cover_url"])
        self.assertEqual(body["description"], self.track["description"])
        self.assertEqual(body["tags"], self.track["tags"])
        self.assertEqual(self.track_by_id(self.track_id), body)

    def test_actual_inner_text_change_is_read_back(self):
        # 用户确实修改名称内部文字或分行后，读回的名称应包含本次改动。
        new_title = "夜航\n第二行：现场录音  定稿"
        status, body = self.patch(self.track_id, {"title": new_title})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["title"], new_title)
        self.assertEqual(self.track_by_id(self.track_id)["title"], new_title)


class EditTitleApiContentRulesTest(ServerTestCase):
    """PATCH title 的保存范围：只去整段首尾空白，内部内容与换行写法保留。"""

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="旧名称", source="/music/title-content.flac",
        )
        self.track_id = self.track["id"]

    def assert_title_saved(self, submitted, expected):
        """提交 submitted，断言成功响应与列表读取的名称都是 expected。"""
        status, body = self.patch(self.track_id, {"title": submitted})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["id"], self.track_id)
        self.assertEqual(
            body["title"], expected,
            "成功响应的名称不一致：\n  实际=%r\n  期望=%r"
            % (body["title"], expected),
        )
        listed = self.track_by_id(self.track_id)["title"]
        self.assertEqual(
            listed, expected,
            "列表读到的名称不一致：\n  实际=%r\n  期望=%r"
            % (listed, expected),
        )

    def test_only_surrounding_whitespace_is_removed(self):
        # 首尾空格、制表符与换行只做整段裁剪。
        self.assert_title_saved(
            "  \t夜航（现场版） \r\n", "夜航（现场版）"
        )

    def test_chinese_quotes_and_angle_brackets_kept_as_plain_text(self):
        # 中文、中英文引号、尖括号都是实际内容，按普通文字保存。
        self.assert_title_saved(
            "它叫“夜航”，又名 \"Night Voyage\" <现场版>",
            "它叫“夜航”，又名 \"Night Voyage\" <现场版>",
        )

    def test_html_looking_text_kept_without_merging_or_stripping(self):
        # 看起来像网页标签的内容不能被剥离或改写。
        self.assert_title_saved(
            "夜航<script>x</script><img src=y>",
            "夜航<script>x</script><img src=y>",
        )

    def test_internal_consecutive_spaces_kept(self):
        # 内部连续空格不能被合并。
        self.assert_title_saved("夜航  现场   版", "夜航  现场   版")

    def test_internal_blank_lines_kept(self):
        # 内部连续空行（多个换行）不能被删除或折叠。
        self.assert_title_saved(
            "夜航\n\n\n现场  版\n结尾",
            "夜航\n\n\n现场  版\n结尾",
        )

    def test_leading_and_trailing_inner_spaces_on_lines_kept(self):
        # 行首行尾的内部空格属于内容；只裁整段首尾，不逐行裁剪。
        self.assert_title_saved(
            "夜航\n  现场版  \n收尾",
            "夜航\n  现场版  \n收尾",
        )

    def test_lf_newlines_preserved_verbatim(self):
        # 直接接口提交的 LF 换行原样保留，不做任何统一。
        title = "夜航\n\n现场  版\n结尾"
        self.assert_title_saved(title, title)
        self.assertNotIn("\r", self.track_by_id(self.track_id)["title"])

    def test_crlf_newlines_preserved_verbatim(self):
        # 直接接口提交的 CRLF 换行原样保留，不能套用网页表单的 LF 归一化。
        title = "夜航\r\n\r\n现场  版\r\n结尾"
        self.assert_title_saved(title, title)
        self.assertIn("\r\n", self.track_by_id(self.track_id)["title"])

    def test_cr_newlines_preserved_verbatim(self):
        # 直接接口提交的旧式 CR 换行也原样保留。
        title = "夜航\r\r现场  版\r结尾"
        self.assert_title_saved(title, title)
        saved = self.track_by_id(self.track_id)["title"]
        self.assertIn("\r", saved)
        self.assertNotIn("\n", saved)

    def test_mixed_newline_styles_each_preserved(self):
        # 同一段名称里混用 LF、CRLF、CR 时，三种写法各自保留。
        title = "LF 行\n下一行\r\n再一行\rCR 行\n收尾"
        self.assert_title_saved(title, title)

    def test_outer_trim_with_internal_crlf_keeps_crlf(self):
        # 只裁整段首尾空白；内部的 CRLF 写法逐字节保留，不被改写成 LF。
        self.assert_title_saved(
            " \r\n夜航\r\n现场  版\r\n ",
            "夜航\r\n现场  版",
        )
        saved = self.track_by_id(self.track_id)["title"]
        self.assertIn("\r\n", saved)
        self.assertNotIn("\n", saved.replace("\r\n", ""))

    def test_newline_style_variants_remain_distinct(self):
        # 仅换行写法不同的两段名称是不同的保存结果，不被统一成同一段。
        lf_title = "夜航\n现场版"
        crlf_title = "夜航\r\n现场版"
        status, body = self.patch(self.track_id, {"title": lf_title})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["title"], lf_title)
        status, body = self.patch(self.track_id, {"title": crlf_title})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["title"], crlf_title)
        self.assertEqual(self.track_by_id(self.track_id)["title"], crlf_title)
        self.assertNotEqual(
            self.track_by_id(self.track_id)["title"], lf_title
        )

    def test_changing_only_line_breaks_is_a_real_change(self):
        # 只调整分行（把一行拆成两行）也属于修改名称：读回应包含新分行。
        track = self.create_track(
            title="夜航现场版", source="/music/linebreak.flac",
        )
        status, body = self.patch(track["id"], {"title": "夜航\n现场版"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["title"], "夜航\n现场版")
        self.assertEqual(self.track_by_id(track["id"])["title"], "夜航\n现场版")


class EditTitleApiPartialUpdateTest(ServerTestCase):
    """局部修改的区别：省略 title 名称完整保留；只提交 title 其他资料保留。"""

    LF_TITLE = "夜航\n\n现场  版\n结尾行"
    CRLF_TITLE = LF_TITLE.replace("\n", "\r\n")
    CR_TITLE = "夜航\r现场  版\r结尾行"

    def make_track(self, title):
        return self.create_track(
            title=title,
            source="/music/partial.flac",
            duration=243.5,
            cover_url="https://img.example/partial.png",
            description="原说明\n第二行",
            tags=["民谣", "现场"],
        )

    # -- 请求省略 title、只修改合法说明：名称完整保留 -----------------------

    def assert_omitting_title_keeps_original(self, original):
        track = self.make_track(original)
        new_description = "只改说明\n保留内部换行"
        status, body = self.patch(track["id"], {
            "description": new_description,
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["id"], track["id"])
        # 省略 title 时名称完整保留，包括原有的内部换行写法。
        self.assertEqual(
            body["title"], original,
            "省略名称后响应中的名称与原文不一致：\n  实际=%r\n  原文=%r"
            % (body["title"], original),
        )
        self.assertEqual(self.track_by_id(track["id"])["title"], original)
        # 同次提交的合法说明正常保存。
        self.assertEqual(body["description"], new_description)

    def test_omitting_title_keeps_lf_text(self):
        self.assert_omitting_title_keeps_original(self.LF_TITLE)

    def test_omitting_title_keeps_crlf_text(self):
        self.assert_omitting_title_keeps_original(self.CRLF_TITLE)

    def test_omitting_title_keeps_cr_text(self):
        self.assert_omitting_title_keeps_original(self.CR_TITLE)

    def test_empty_patch_body_keeps_multiline_title(self):
        track = self.make_track(self.CRLF_TITLE)
        status, body = self.patch(track["id"], {})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["title"], self.CRLF_TITLE)
        self.assertEqual(self.track_by_id(track["id"]), track)

    def test_omitting_title_while_changing_other_fields_keeps_every_newline(self):
        # 同时修改说明、时长与标签但省略名称，三种换行写法的名称都逐字节保留。
        for index, original in enumerate(
            (self.LF_TITLE, self.CRLF_TITLE, self.CR_TITLE)
        ):
            with self.subTest(case=("lf", "crlf", "cr")[index]):
                track = self.create_track(
                    title=original,
                    source=f"/music/omit-title-{index}.flac",
                    description="旧说明",
                )
                status, body = self.patch(track["id"], {
                    "description": "新说明",
                    "duration": 9,
                    "tags": ["新标签"],
                })
                self.assertEqual(status, 200, body)
                self.assertEqual(body["title"], original)
                self.assertEqual(
                    self.track_by_id(track["id"])["title"], original
                )

    # -- 只提交新名称：采用本次名称，其余资料保留原值 -----------------------

    def test_title_only_adopts_new_name_and_keeps_other_fields(self):
        track = self.make_track(self.CRLF_TITLE)
        new_title = "夜航·定稿\n第二行"
        status, body = self.patch(track["id"], {"title": new_title})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["id"], track["id"])
        # 采用本次提交的名称（接口不做换行统一，这里提交 LF 即为 LF）。
        self.assertEqual(body["title"], new_title)
        # 来源、时长、封面、说明和标签保留原值。
        self.assertEqual(body["source"], track["source"])
        self.assertEqual(body["duration"], track["duration"])
        self.assertEqual(body["cover_url"], track["cover_url"])
        self.assertEqual(body["description"], track["description"])
        self.assertEqual(body["tags"], track["tags"])
        self.assertEqual(self.track_by_id(track["id"]), body)

    def test_title_only_with_crlf_adopts_crlf(self):
        # 直接接口改名：提交的 CRLF 名称按 CRLF 保存，其余资料不动。
        track = self.make_track("旧名称")
        new_title = "新名称\r\n第二行"
        status, body = self.patch(track["id"], {"title": new_title})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["title"], new_title)
        self.assertEqual(self.track_by_id(track["id"])["title"], new_title)
        self.assertEqual(body["source"], track["source"])
        self.assertEqual(body["tags"], track["tags"])


class EditTitleApiSameSourceVersionsTest(ServerTestCase):
    """同一来源的多个独立版本：只给一条改名，不误报冲突，其他版本不变。"""

    def setUp(self):
        super().setUp()
        self.first = self.create_track(
            title="夜航·首版",
            source="/music/yehang.flac",
            duration=243.5,
            cover_url="https://img.example/yehang.png",
            description="首版说明",
            tags=["民谣", "现场"],
        )
        self.second = self.create_track(
            title="夜航·重制",
            source="/music/yehang.flac",
            duration=250,
            cover_url="https://img.example/yehang-remaster.png",
            description="重制说明",
            tags=["民谣", "重制"],
            save_as_new_version=True,
        )
        self.third = self.create_track(
            title="无关曲目", source="/music/other.flac",
            description="其他来源",
        )

    def test_rename_one_version_succeeds_without_conflict(self):
        new_title = "夜航·重制（更名）"
        status, body = self.patch(self.second["id"], {"title": new_title})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["id"], self.second["id"])
        # 只改名称、来源未动，即使多个版本共用同一来源也不报来源冲突。
        self.assertEqual(body["source"], "/music/yehang.flac")
        self.assertEqual(body["title"], new_title)
        self.assertNotIn("existing", body)

    def test_other_versions_full_records_untouched(self):
        status, body = self.patch(
            self.second["id"], {"title": "夜航·重制（更名）"}
        )
        self.assertEqual(status, 200, body)
        tracks = self.list_tracks()
        # 记录数量与列表顺序不变，仍是各自独立的记录。
        self.assertEqual(
            [t["id"] for t in tracks],
            [self.first["id"], self.second["id"], self.third["id"]],
        )
        # 被修改的版本与成功响应一致。
        self.assertEqual(self.track_by_id(self.second["id"]), body)
        # 同一来源的其他版本的名称与完整资料不受影响。
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)
        # 其他来源的曲目也不受影响。
        self.assertEqual(self.track_by_id(self.third["id"]), self.third)

    def test_rename_every_version_independently(self):
        # 依次修改同一来源各版本的名称，各自只影响自己的标识。
        status, body = self.patch(self.first["id"], {"title": "首版更名"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["title"], "首版更名")
        status, body = self.patch(
            self.second["id"], {"title": "重制更名\r\n保留 CRLF"}
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["title"], "重制更名\r\n保留 CRLF")
        self.assertEqual(self.track_by_id(self.first["id"])["title"], "首版更名")
        self.assertEqual(
            self.track_by_id(self.second["id"])["title"],
            "重制更名\r\n保留 CRLF",
        )
        self.assertEqual(self.track_by_id(self.third["id"])["title"], "无关曲目")

    def test_rename_to_the_other_versions_title_does_not_merge(self):
        # 把其中一条改成与另一版本完全相同的名称：记录仍各自独立，不合并。
        status, body = self.patch(
            self.second["id"], {"title": self.first["title"]}
        )
        self.assertEqual(status, 200, body)
        tracks = self.list_tracks()
        self.assertEqual(
            [t["id"] for t in tracks],
            [self.first["id"], self.second["id"], self.third["id"]],
        )
        self.assertEqual(
            self.track_by_id(self.first["id"])["title"], self.first["title"]
        )
        self.assertEqual(
            self.track_by_id(self.second["id"])["title"], self.first["title"]
        )
        self.assertNotEqual(self.first["id"], self.second["id"])


class EditTitleApiSameTitleRecordsTest(ServerTestCase):
    """名称相同的不同曲目：改名不会把记录合并，标识各自保持。"""

    def setUp(self):
        super().setUp()
        # 名称相同但来源不同：两条独立记录。
        self.first = self.create_track(
            title="同名曲目", source="/music/a.flac",
            duration=100, description="甲的说明", tags=["甲"],
        )
        self.second = self.create_track(
            title="同名曲目", source="/music/b.flac",
            duration=200, description="乙的说明", tags=["乙"],
        )

    def test_same_title_records_stay_distinct(self):
        tracks = self.list_tracks()
        self.assertEqual(len(tracks), 2)
        self.assertNotEqual(self.first["id"], self.second["id"])
        self.assertEqual(
            [t["id"] for t in tracks],
            [self.first["id"], self.second["id"]],
        )

    def test_rename_one_does_not_merge_or_touch_the_other(self):
        status, body = self.patch(
            self.first["id"], {"title": "同名曲目·改名"}
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["id"], self.first["id"])
        tracks = self.list_tracks()
        # 仍是两条独立记录，顺序不变，没有合并。
        self.assertEqual(len(tracks), 2)
        self.assertEqual(
            [t["id"] for t in tracks],
            [self.first["id"], self.second["id"]],
        )
        self.assertEqual(
            self.track_by_id(self.first["id"])["title"], "同名曲目·改名"
        )
        # 另一条同名记录的名称与完整资料保持原样。
        self.assertEqual(self.track_by_id(self.second["id"]), self.second)

    def test_rename_one_to_a_third_shared_title_keeps_both_ids(self):
        # 两条都改成另一个相同名称，也仍然各自占用自己的标识。
        third = self.create_track(
            title="参照物", source="/music/c.flac",
        )
        for record in (self.first, self.second):
            status, body = self.patch(
                record["id"], {"title": "另一个共同名称"}
            )
            self.assertEqual(status, 200, body)
            self.assertEqual(body["id"], record["id"])
        tracks = self.list_tracks()
        self.assertEqual(
            [t["id"] for t in tracks],
            [self.first["id"], self.second["id"], third["id"]],
        )
        self.assertEqual(
            [t["title"] for t in tracks[:2]],
            ["另一个共同名称", "另一个共同名称"],
        )


class EditTitleApiInvalidTest(ServerTestCase):
    """PATCH title 为空/纯空白或非字符串：400 且 field=title，整单失败。"""

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="夜航",
            source="/music/yehang.flac",
            duration=243.5,
            cover_url="https://img.example/yehang.png",
            description="原说明\n第二行",
            tags=["民谣", "现场"],
        )
        self.track_id = self.track["id"]
        # 同一来源的另一版本与另一来源曲目，用于核对失败不波及其他记录。
        self.bystander = self.create_track(
            title="同来源另一版本",
            source="/music/yehang.flac",
            duration=250,
            description="同来源版本说明",
            tags=["其他"],
            save_as_new_version=True,
        )
        self.other = self.create_track(
            title="别的来源", source="/music/other.flac",
            description="不应受影响",
        )

    def assert_title_rejected(self, payload):
        """非法 title（连同合法的新说明等资料）必须整单失败。"""
        status, body = self.patch(self.track_id, payload)
        self.assertEqual(status, 400, body)
        # field 指向 title，错误文字说明名称有误。
        self.assertEqual(body["field"], "title")
        self.assertIn("名称", body["error"])
        # 绝不是来源冲突响应。
        self.assertNotIn("existing", body)

    def assert_everything_unchanged(self):
        tracks = self.list_tracks()
        # 不新增记录、不改变列表顺序。
        self.assertEqual(
            [t["id"] for t in tracks],
            [self.track_id, self.bystander["id"], self.other["id"]],
        )
        # 目标曲目完整资料保持提交前内容：同次请求里合法的新说明等
        # 资料没有先写入，原名称仍在。
        self.assertEqual(self.track_by_id(self.track_id), self.track)
        # 同一来源的其他版本与其他来源曲目都不受影响。
        self.assertEqual(self.track_by_id(self.bystander["id"]), self.bystander)
        self.assertEqual(self.track_by_id(self.other["id"]), self.other)

    def test_empty_string_is_rejected(self):
        self.assert_title_rejected({"title": ""})
        self.assert_everything_unchanged()

    def test_whitespace_only_titles_are_rejected(self):
        # 只含空格、制表符或换行（及其组合、含 CRLF/CR）都拒绝。
        for bad in (" ", "\t", "  \t ", "\n", "\r\n", "\r", " \n\t\r\n "):
            with self.subTest(bad=repr(bad)):
                self.assert_title_rejected({"title": bad})
                self.assert_everything_unchanged()

    def test_null_is_rejected(self):
        # 名称没有“清空”语义：null 也返回 400 而不是保存空名称。
        self.assert_title_rejected({"title": None})
        self.assert_everything_unchanged()

    def test_number_types_are_rejected(self):
        for bad in (0, 1, 243, 243.5, -3):
            with self.subTest(bad=bad):
                self.assert_title_rejected({"title": bad})
                self.assert_everything_unchanged()

    def test_booleans_are_rejected(self):
        for bad in (True, False):
            with self.subTest(bad=bad):
                self.assert_title_rejected({"title": bad})
                self.assert_everything_unchanged()

    def test_array_and_object_are_rejected(self):
        for bad in ([], ["名称"], {}, {"title": "名称"}):
            with self.subTest(bad=bad):
                self.assert_title_rejected({"title": bad})
                self.assert_everything_unchanged()

    def test_invalid_title_with_valid_description_saves_nothing(self):
        # 即使同次请求还提交了合法的新说明与其他合法资料，也不能先保存
        # 说明或其他部分内容。
        self.assert_title_rejected({
            "title": "   ",
            "description": "不应保存的新说明",
            "duration": 300,
            "cover_url": "https://img.example/should-not-save.png",
            "tags": ["不应保存的新标签"],
        })
        self.assert_everything_unchanged()
        # 明确核对原说明仍在，而不是部分修改后的结果。
        self.assertEqual(
            self.track_by_id(self.track_id)["description"], "原说明\n第二行"
        )

    def test_null_title_with_valid_description_saves_nothing(self):
        self.assert_title_rejected({
            "title": None,
            "description": "不应保存的新说明",
        })
        self.assert_everything_unchanged()

    def test_invalid_title_alone_is_rejected(self):
        # 即使请求中只有出错的 title 字段，规则也相同。
        self.assert_title_rejected({"title": ["数组"]})
        self.assert_everything_unchanged()

    def test_legal_request_after_rejection_saves_normally(self):
        # 非法名称被拒后，用同一标识提交合法名称可以正常保存；
        # 失败请求里尝试一起改的说明不会被补入。
        status, body = self.patch(self.track_id, {
            "title": 123,
            "description": "不应保存的说明",
        })
        self.assertEqual(status, 400, body)
        self.assertEqual(body["field"], "title")

        status, body = self.patch(
            self.track_id, {"title": "夜航（修正版）"}
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["title"], "夜航（修正版）")
        # 说明没有被失败请求改动。
        self.assertEqual(body["description"], self.track["description"])
        self.assertEqual(self.track_by_id(self.track_id), body)

    def test_repeated_failures_leave_no_partial_change_or_extra_record(self):
        # 连续多次非法名称后，列表仍是提交前的记录与原名称，
        # 不出现部分修改或额外记录。
        for bad in ("", "  \t ", None, 1, False, ["x"], {"k": "v"}):
            with self.subTest(bad=repr(bad)):
                self.assert_title_rejected({
                    "title": bad,
                    "description": "反复失败也不应保存的说明",
                })
                self.assert_everything_unchanged()


class EditCoverApiOnlyFieldTest(ServerTestCase):
    """PATCH 只提交 cover_url：更新原记录，200 与完整资料，列表一致、次序不变。"""

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="夜航",
            source="/music/yehang.flac",
            duration=243.5,
            cover_url="https://img.example/yehang.png",
            description="旧说明",
            tags=["民谣", "现场"],
        )
        self.track_id = self.track["id"]
        # 一首无关曲目：改封面不能影响它，也不能改变列表按标识升序的关系。
        self.bystander = self.create_track(
            title="无关曲目", source="/music/other.flac", duration=7,
            cover_url="https://img.example/other.png",
        )

    def test_cover_only_returns_200_with_full_record(self):
        new_cover = "https://img.example/yehang-remaster.png"
        status, body = self.patch(self.track_id, {"cover_url": new_cover})
        self.assertEqual(status, 200, body)
        # 成功响应是修改后的完整曲目，曲目标识保持不变。
        self.assertEqual(body, {
            "id": self.track_id,
            "title": "夜航",
            "source": "/music/yehang.flac",
            "duration": 243.5,
            "cover_url": new_cover,
            "description": "旧说明",
            "tags": ["民谣", "现场"],
        })

    def test_listed_cover_matches_success_response(self):
        new_cover = "https://img.example/final.png"
        status, body = self.patch(self.track_id, {"cover_url": new_cover})
        self.assertEqual(status, 200, body)
        # 随后从曲目列表接口读到的记录与成功响应完全一致。
        self.assertEqual(self.track_by_id(self.track_id), body)
        self.assertEqual(self.track_by_id(self.track_id)["cover_url"], new_cover)

    def test_only_cover_changes_other_fields_keep_values(self):
        status, body = self.patch(self.track_id, {"cover_url": "换个地址"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["id"], self.track_id)
        # 名称、来源、时长、说明和标签继续保留原值。
        self.assertEqual(body["title"], self.track["title"])
        self.assertEqual(body["source"], self.track["source"])
        self.assertEqual(body["duration"], self.track["duration"])
        self.assertEqual(body["description"], self.track["description"])
        self.assertEqual(body["tags"], self.track["tags"])
        self.assertEqual(self.track_by_id(self.track_id), body)

    def test_record_count_and_list_order_unchanged(self):
        before_ids = [t["id"] for t in self.list_tracks()]
        self.assertEqual(before_ids, [self.track_id, self.bystander["id"]])
        status, body = self.patch(self.track_id, {"cover_url": "换个地址"})
        self.assertEqual(status, 200, body)
        # 记录数量与列表顺序不变，只是原标识的资料被更新。
        self.assertEqual([t["id"] for t in self.list_tracks()], before_ids)
        # 其他曲目完整资料不受影响。
        self.assertEqual(self.track_by_id(self.bystander["id"]), self.bystander)

    def test_fill_cover_on_track_without_cover(self):
        # 原本没有封面地址的曲目可以正常补填。
        track = self.create_track(
            title="无封面", source="/music/no-cover.flac", cover_url="",
        )
        status, body = self.patch(track["id"], {
            "cover_url": "https://img.example/fill.png",
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["cover_url"], "https://img.example/fill.png")
        self.assertEqual(
            self.track_by_id(track["id"])["cover_url"],
            "https://img.example/fill.png",
        )


class EditCoverApiVerbatimTextTest(ServerTestCase):
    """PATCH cover_url 非空文字：只裁整段首尾空白，内部文字逐字保留。"""

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="原文保留", source="/music/cover.flac",
            cover_url="https://img.example/old.png",
        )
        self.track_id = self.track["id"]

    def assert_cover_saved(self, submitted, expected):
        status, body = self.patch(self.track_id, {"cover_url": submitted})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["id"], self.track_id)
        self.assertEqual(
            body["cover_url"], expected,
            "成功响应的封面地址与期望不一致：\n  实际=%r\n  期望=%r"
            % (body["cover_url"], expected),
        )
        listed = self.track_by_id(self.track_id)["cover_url"]
        self.assertEqual(
            listed, expected,
            "列表读到的封面地址与期望不一致：\n  实际=%r\n  期望=%r"
            % (listed, expected),
        )

    def test_chinese_quotes_and_angle_brackets_kept(self):
        # 中文、中英文引号、尖括号都属于封面地址文字，按普通文字保存。
        self.assert_cover_saved(
            '封面：《夜航》“现场版” "Live" <内部>文字',
            '封面：《夜航》“现场版” "Live" <内部>文字',
        )

    def test_text_that_does_not_look_like_url_is_accepted(self):
        # 封面地址只是一段资料：不因看起来不像网址而拒绝保存。
        text = "这不是网址，而是一整段 封面 说明文字"
        self.assert_cover_saved(text, text)

    def test_multiple_url_looking_lines_kept_as_one_value(self):
        # 即使多行各自看起来像地址，也只保存为一个封面地址值，绝不拆分。
        text = "https://a.example/1.png\nhttps://b.example/2.png"
        status, body = self.patch(self.track_id, {"cover_url": text})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["cover_url"], text)
        self.assertIsInstance(body["cover_url"], str)
        listed = self.track_by_id(self.track_id)
        self.assertEqual(listed["cover_url"], text)
        self.assertNotIsInstance(listed["cover_url"], list)

    def test_only_surrounding_whitespace_trimmed(self):
        # 只去掉整段文字的首尾空白；内部空格与行首空格逐字保留。
        self.assert_cover_saved(
            "  https://img.example/a  \n  第二行还有空格  \n ",
            "https://img.example/a  \n  第二行还有空格",
        )

    def test_leading_and_trailing_newlines_trimmed(self):
        self.assert_cover_saved(
            "\n\nhttps://img.example/a\n\n",
            "https://img.example/a",
        )

    def test_tabs_and_spaces_trimmed_only_at_ends(self):
        self.assert_cover_saved(
            "\t https://img.example/a\t内部制表\t \t",
            "https://img.example/a\t内部制表",
        )

    def test_internal_blank_lines_and_spaces_kept(self):
        # 段落之间的连续空行与内部空格不能被折叠。
        text = "第一段\n\n\n  空行后的段落  \n再一行"
        self.assert_cover_saved(text, text)

    def test_lf_newlines_preserved_verbatim(self):
        # 直接接口提交的 LF 换行原样保留，不做任何统一。
        text = "第一行\n第二行\n\n第四行"
        self.assert_cover_saved(text, text)
        self.assertNotIn("\r", self.track_by_id(self.track_id)["cover_url"])

    def test_crlf_newlines_preserved_verbatim(self):
        # 直接接口提交的 CRLF 换行原样保留，不能套用网页表单的 LF 归一化。
        text = "第一行\r\n第二行\r\n\r\n第四行"
        self.assert_cover_saved(text, text)
        self.assertIn("\r\n", self.track_by_id(self.track_id)["cover_url"])

    def test_cr_newlines_preserved_verbatim(self):
        # 直接接口提交的旧式 CR 换行也原样保留。
        text = "第一行\r第二行\r\r第四行"
        self.assert_cover_saved(text, text)
        saved = self.track_by_id(self.track_id)["cover_url"]
        self.assertIn("\r", saved)
        self.assertNotIn("\n", saved)

    def test_mixed_newline_styles_each_preserved(self):
        # 同一段文字里混用 LF、CRLF、CR 时，三种写法各自保留。
        text = "LF\n下一行\r\n再一行\rCR 行\n收尾"
        self.assert_cover_saved(text, text)

    def test_newline_only_variants_stay_distinct(self):
        # 仅换行写法不同的两段地址各自保留，不被网页式换行归一合并。
        lf_text = "甲\n乙"
        crlf_text = "甲\r\n乙"
        status, body = self.patch(self.track_id, {"cover_url": lf_text})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["cover_url"], lf_text)
        status, body = self.patch(self.track_id, {"cover_url": crlf_text})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["cover_url"], crlf_text)
        self.assertNotEqual(
            self.track_by_id(self.track_id)["cover_url"], lf_text
        )


class EditCoverApiOmitAndClearTest(ServerTestCase):
    """省略 cover_url 保留旧地址；空串/纯空白/null 主动清空为空字符串。

    原本有地址（含内部换行写法）与原本为空的曲目都遵守相同规则。
    """

    # -- 修改其他合法资料但省略 cover_url：原地址完整保留 ------------------

    def assert_omitting_cover_keeps_original(self, original, *, source):
        track = self.create_track(
            title="省略封面", source=source, cover_url=original,
            duration=100, description="旧说明", tags=["旧标签"],
        )
        status, body = self.patch(track["id"], {
            "title": "新名称",
            "duration": 9,
            "description": "新说明",
            "tags": ["新标签"],
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["id"], track["id"])
        # 省略 cover_url 时，原有地址或空值都完整保留。
        self.assertEqual(
            body["cover_url"], original,
            "省略封面地址后响应值与原文不一致：\n  实际=%r\n  原文=%r"
            % (body["cover_url"], original),
        )
        self.assertEqual(
            self.track_by_id(track["id"])["cover_url"], original
        )
        # 同次提交的其他合法资料正常保存。
        self.assertEqual(body["title"], "新名称")
        self.assertEqual(body["duration"], 9)
        self.assertEqual(body["description"], "新说明")
        self.assertEqual(body["tags"], ["新标签"])

    def test_omitting_cover_keeps_existing_url(self):
        # 原来有地址的不能被清空。
        self.assert_omitting_cover_keeps_original(
            "https://img.example/keep.png", source="/music/omit-url.flac"
        )

    def test_omitting_cover_keeps_multiline_old_value_bytes(self):
        # 原有地址内部使用的 LF/CRLF/CR 写法不能因省略提交而被改写。
        self.assert_omitting_cover_keeps_original(
            "旧地址\r\n第二行\n第三段\r结尾",
            source="/music/omit-multiline.flac",
        )

    def test_omitting_cover_keeps_empty_string(self):
        # 原来为空的也继续为空。
        self.assert_omitting_cover_keeps_original(
            "", source="/music/omit-empty.flac"
        )

    def test_empty_patch_body_keeps_cover(self):
        track = self.create_track(
            title="空请求", source="/music/empty-patch.flac",
            cover_url="https://img.example/keep.png",
        )
        status, body = self.patch(track["id"], {})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["cover_url"], "https://img.example/keep.png")
        self.assertEqual(self.track_by_id(track["id"]), track)

    # -- 明确清空：空串、仅含空格或换行的字符串、null 都保存为空字符串 -----

    def test_empty_string_whitespace_and_null_clear_existing(self):
        clear_values = (
            "", "   ", "\t", "\n", "\r\n", "\r", "\n\n\n", " \n\t \r\n ",
        )
        for index, value in enumerate(clear_values):
            with self.subTest(value=repr(value)):
                track = self.create_track(
                    title=f"主动清空-{index}",
                    source=f"/music/clear-{index}.flac",
                    cover_url="https://img.example/old.png",
                )
                status, body = self.patch(track["id"], {"cover_url": value})
                self.assertEqual(status, 200, body)
                # 成功后 cover_url 是空字符串，而不是 null，也不是旧地址。
                self.assertEqual(body["cover_url"], "")
                self.assertIsNotNone(body["cover_url"])
                self.assertIsInstance(body["cover_url"], str)
                self.assertEqual(
                    self.track_by_id(track["id"])["cover_url"], ""
                )

    def test_null_clears_existing(self):
        track = self.create_track(
            title="null 清空", source="/music/clear-null.flac",
            cover_url="https://img.example/old.png",
        )
        status, body = self.patch(track["id"], {"cover_url": None})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["cover_url"], "")
        self.assertEqual(self.track_by_id(track["id"])["cover_url"], "")

    def test_clear_submissions_accepted_when_already_empty(self):
        # 原本没有封面地址的曲目同样接受这些清空提交，结果仍是空字符串。
        for index, value in enumerate(("", "   ", "\n \r\n\t", None)):
            with self.subTest(value=repr(value)):
                track = self.create_track(
                    title=f"本就为空-{index}",
                    source=f"/music/empty-already-{index}.flac",
                    cover_url="",
                )
                status, body = self.patch(track["id"], {"cover_url": value})
                self.assertEqual(status, 200, body)
                self.assertEqual(body["cover_url"], "")
                self.assertEqual(
                    self.track_by_id(track["id"])["cover_url"], ""
                )

    def test_clearing_cover_saves_together_with_other_fields(self):
        # 清空地址与同次提交的其他合法资料一起保存。
        track = self.create_track(
            title="旧名称", source="/music/clear-with.flac",
            duration=100, cover_url="https://img.example/old.png",
            description="旧说明", tags=["旧标签"],
        )
        status, body = self.patch(track["id"], {
            "cover_url": "  \n  ",
            "title": "新名称",
            "duration": 243.5,
            "description": "新说明",
            "tags": ["新标签"],
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["cover_url"], "")
        self.assertEqual(body["title"], "新名称")
        self.assertEqual(body["duration"], 243.5)
        self.assertEqual(body["description"], "新说明")
        self.assertEqual(body["tags"], ["新标签"])
        self.assertEqual(self.track_by_id(track["id"]), body)

    def test_null_cover_alongside_other_changes_clears_and_saves_others(self):
        track = self.create_track(
            title="旧名称", source="/music/null-with.flac",
            cover_url="https://img.example/old.png",
        )
        status, body = self.patch(track["id"], {
            "cover_url": None,
            "title": "清空地址版",
            "duration": 12,
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["cover_url"], "")
        self.assertEqual(body["title"], "清空地址版")
        self.assertEqual(body["duration"], 12)
        self.assertEqual(self.track_by_id(track["id"]), body)

    def test_clear_then_refill_round_trips_on_same_id(self):
        # 地址 -> 清空 -> 再补填，都在同一标识上生效，响应与列表始终一致。
        track = self.create_track(
            title="往返", source="/music/round.flac",
            cover_url="https://img.example/first.png",
        )
        status, body = self.patch(track["id"], {"cover_url": None})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["cover_url"], "")
        status, body = self.patch(track["id"], {
            "cover_url": "https://img.example/second.png",
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["cover_url"], "https://img.example/second.png")
        self.assertEqual(
            self.track_by_id(track["id"])["cover_url"],
            "https://img.example/second.png",
        )


class EditCoverApiSameSourceVersionsTest(ServerTestCase):
    """同一来源的多个版本：只改一条的封面地址，其他版本完整资料不变。"""

    def setUp(self):
        super().setUp()
        self.first = self.create_track(
            title="夜航·首版",
            source="/music/yehang.flac",
            duration=243.5,
            cover_url="https://img.example/yehang.png",
            description="首版说明",
            tags=["民谣", "现场"],
        )
        self.second = self.create_track(
            title="夜航·重制",
            source="/music/yehang.flac",
            duration=250,
            cover_url="https://img.example/yehang-remaster.png",
            description="重制说明",
            tags=["民谣", "重制"],
            save_as_new_version=True,
        )
        self.third = self.create_track(
            title="无关曲目", source="/music/other.flac",
            cover_url="https://img.example/other.png",
        )

    def test_edit_one_versions_cover_succeeds_without_conflict(self):
        status, body = self.patch(self.second["id"], {
            "cover_url": "https://img.example/remaster-v2.png",
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["id"], self.second["id"])
        self.assertEqual(body["source"], "/music/yehang.flac")
        self.assertEqual(
            body["cover_url"], "https://img.example/remaster-v2.png"
        )
        # 来源未改，只改封面地址不会触发同来源冲突。

    def test_other_versions_full_records_untouched(self):
        status, body = self.patch(self.second["id"], {
            "cover_url": "  重制版新地址\r\n第二行  ",
        })
        self.assertEqual(status, 200, body)
        tracks = self.list_tracks()
        # 记录数量与列表顺序不变，仍是各自独立的记录。
        self.assertEqual(
            [t["id"] for t in tracks],
            [self.first["id"], self.second["id"], self.third["id"]],
        )
        # 被修改的版本与成功响应一致（首尾空白已裁掉，内部 CRLF 保留）。
        self.assertEqual(self.track_by_id(self.second["id"]), body)
        self.assertEqual(
            body["cover_url"], "重制版新地址\r\n第二行"
        )
        # 同一来源的其他版本完整资料不受影响。
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)
        # 其他来源的曲目也不受影响。
        self.assertEqual(self.track_by_id(self.third["id"]), self.third)

    def test_edit_cover_of_every_version_independently(self):
        # 依次修改同一来源各版本的封面，各自只影响自己的标识。
        status, body = self.patch(self.first["id"], {
            "cover_url": "首版新地址",
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["cover_url"], "首版新地址")
        status, body = self.patch(self.second["id"], {
            "cover_url": "重制新地址\r\n保留 CRLF",
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["cover_url"], "重制新地址\r\n保留 CRLF")
        self.assertEqual(
            self.track_by_id(self.first["id"])["cover_url"], "首版新地址"
        )
        self.assertEqual(
            self.track_by_id(self.second["id"])["cover_url"],
            "重制新地址\r\n保留 CRLF",
        )
        self.assertEqual(
            self.track_by_id(self.third["id"])["cover_url"],
            "https://img.example/other.png",
        )

    def test_clear_one_version_cover_leaves_others_intact(self):
        # 清空其中一条的封面，其他版本的封面仍完整保留。
        status, body = self.patch(self.first["id"], {"cover_url": ""})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["cover_url"], "")
        self.assertEqual(
            self.track_by_id(self.first["id"])["cover_url"], ""
        )
        self.assertEqual(
            self.track_by_id(self.second["id"])["cover_url"],
            "https://img.example/yehang-remaster.png",
        )


class EditCoverApiInvalidTypeTest(ServerTestCase):
    """PATCH cover_url 误传非字符串类型：400 field=cover_url，整单不保存。"""

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="夜航",
            source="/music/yehang.flac",
            duration=243.5,
            cover_url="https://img.example/yehang.png",
            description="原说明\n第二行",
            tags=["民谣", "现场"],
        )
        self.track_id = self.track["id"]
        # 同一来源的另一版本与别的来源曲目，用于证明拒绝不波及其他记录。
        self.bystander = self.create_track(
            title="无关曲目",
            source="/music/yehang.flac",
            duration=250,
            cover_url="https://img.example/other-version.png",
            description="同一来源的另一版本",
            tags=["其他"],
            save_as_new_version=True,
        )
        self.other = self.create_track(
            title="别的来源", source="/music/other.flac",
            cover_url="https://img.example/other-source.png",
        )

    def assert_cover_rejected(self, payload):
        status, body = self.patch(self.track_id, payload)
        self.assertEqual(status, 400, body)
        # field 指向 cover_url，错误文字明确指出封面地址类型有误。
        self.assertEqual(body["field"], "cover_url")
        self.assertIn("封面", body["error"])

    def assert_everything_unchanged(self):
        tracks = self.list_tracks()
        # 不新增记录、不改变列表顺序。
        self.assertEqual(
            [t["id"] for t in tracks],
            [self.track_id, self.bystander["id"], self.other["id"]],
        )
        # 目标曲目完整资料保持提交前内容：原封面地址仍在，同次请求里
        # 合法的新名称等资料没有先写入。
        self.assertEqual(self.track_by_id(self.track_id), self.track)
        # 同一来源的其他版本与其他来源曲目都不受影响。
        self.assertEqual(self.track_by_id(self.bystander["id"]), self.bystander)
        self.assertEqual(self.track_by_id(self.other["id"]), self.other)

    def test_number_types_are_rejected(self):
        for bad in (0, 1, 243, 243.5, -3):
            with self.subTest(bad=bad):
                self.assert_cover_rejected({"cover_url": bad})
                self.assert_everything_unchanged()

    def test_booleans_are_rejected(self):
        for bad in (True, False):
            with self.subTest(bad=bad):
                self.assert_cover_rejected({"cover_url": bad})
                self.assert_everything_unchanged()

    def test_arrays_and_objects_are_rejected(self):
        for bad in ([], ["https://a/1.png"], {}, {"url": "https://a/1.png"}):
            with self.subTest(bad=bad):
                self.assert_cover_rejected({"cover_url": bad})
                self.assert_everything_unchanged()

    def test_invalid_cover_with_valid_title_and_duration_saves_nothing(self):
        # 即使同次请求还填写了合法的新名称或时长，也不能先保存其中一部分。
        self.assert_cover_rejected({
            "cover_url": 123,
            "title": "不应保存的新名称",
            "duration": 300,
            "description": "不应保存的新说明",
            "tags": ["不应保存的新标签"],
        })
        self.assert_everything_unchanged()
        # 明确核对原封面地址仍在，而不是部分修改后的结果。
        self.assertEqual(
            self.track_by_id(self.track_id)["cover_url"],
            "https://img.example/yehang.png",
        )

    def test_invalid_cover_alone_is_rejected(self):
        # 即使请求中只有出错的 cover_url 字段，规则也相同。
        self.assert_cover_rejected({"cover_url": ["数组"]})
        self.assert_everything_unchanged()

    def test_null_is_clear_not_type_error(self):
        # null 的清空含义不能混入类型错误：null 返回 200 并清空为空串。
        status, body = self.patch(self.track_id, {"cover_url": None})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["cover_url"], "")
        self.assertEqual(self.track_by_id(self.track_id)["cover_url"], "")

    def test_null_alongside_other_changes_clears_and_saves_others(self):
        # null 与其他合法字段一起提交时，封面清空且其他字段正常保存。
        status, body = self.patch(self.track_id, {
            "title": "夜航（清空封面版）",
            "cover_url": None,
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["title"], "夜航（清空封面版）")
        self.assertEqual(body["cover_url"], "")
        self.assertEqual(
            self.track_by_id(self.track_id)["cover_url"], ""
        )

    def test_legal_request_after_type_error_saves_normally(self):
        # 类型错误被拒后，用同一标识提交合法封面可以正常保存；
        # 失败请求里尝试一起改的名称不会被补入。
        status, body = self.patch(self.track_id, {
            "title": "不应保存的名称",
            "cover_url": True,
        })
        self.assertEqual(status, 400, body)
        self.assertEqual(body["field"], "cover_url")

        status, body = self.patch(
            self.track_id, {"cover_url": "https://img.example/fixed.png"}
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["cover_url"], "https://img.example/fixed.png")
        # 名称没有被失败请求改动。
        self.assertEqual(body["title"], self.track["title"])
        self.assertEqual(self.track_by_id(self.track_id), body)

    def test_repeated_type_errors_leave_no_partial_change(self):
        # 连续多次类型错误后，列表仍是提交前的记录与原封面，
        # 不出现部分修改或额外记录。
        for bad in (1, False, ["x"], {"k": "v"}):
            with self.subTest(bad=bad):
                self.assert_cover_rejected({
                    "title": "反复失败也不应保存的名称",
                    "cover_url": bad,
                })
                self.assert_everything_unchanged()

    def test_valid_cover_with_negative_duration_rejects_whole_request(self):
        # 封面地址合法但同次提交了负数时长：整次拒绝，错误指向时长，
        # 原封面地址仍保留，同次的其他合法修改也不写入。
        status, body = self.patch(self.track_id, {
            "cover_url": "https://img.example/should-not-save.png",
            "title": "不应保存的新名称",
            "duration": -1,
        })
        self.assertEqual(status, 400, body)
        self.assertEqual(body["field"], "duration")
        self.assertIn("时长", body["error"])
        self.assert_everything_unchanged()
        self.assertEqual(
            self.track_by_id(self.track_id)["cover_url"],
            "https://img.example/yehang.png",
        )

    def test_clear_cover_with_negative_duration_rejects_whole_request(self):
        # 即使封面是主动清空，同次时长非法时也整次拒绝，封面不被清空。
        status, body = self.patch(self.track_id, {
            "cover_url": "",
            "duration": -2.5,
        })
        self.assertEqual(status, 400, body)
        self.assertEqual(body["field"], "duration")
        self.assert_everything_unchanged()
        self.assertEqual(
            self.track_by_id(self.track_id)["cover_url"],
            "https://img.example/yehang.png",
        )


class _BadRequestBodyFixture(ServerTestCase):
    """请求体格式回归的共同夹具：资料丰富的目标曲目、同来源独立版本、
    无关曲目各一条；任何失败后整个列表都必须与快照逐字一致。"""

    def setUp(self):
        super().setUp()
        # 目标曲目：说明含中文、段落间空行与结尾空行；标签含内部空格、
        # 中英文逗号/顿号与项内换行，先后关系也是要保留的资料。
        self.track_v1 = self.create_track(
            title="夜航",
            source="/music/yehang.flac",
            duration=243.5,
            cover_url="https://img.example/yehang.png",
            description="第一段说明\n\n第二段：含中文与标点！\n\n",
            tags=["民谣", "现场  录音", "逗号,标签", "顿号、标签", "多行\n标签"],
        )
        self.track_id = self.track_v1["id"]
        # 同一来源的另一个独立版本：失败后它的资料也必须逐字保持原样。
        self.track_v2 = self.create_track(
            title="夜航（现场版）",
            source="/music/yehang.flac",
            duration=300,
            description="第二版说明\n\n版本二空行后的文字",
            tags=["版本二", "民谣"],
            save_as_new_version=True,
        )
        # 不同来源的无关曲目，用于核对数量、次序与其他记录不受影响。
        self.bystander = self.create_track(
            title="无关曲目",
            source="/music/other.flac",
            duration=7,
            description="其他来源的说明",
            tags=["其他"],
        )
        self.expected = self.list_tracks()
        self.expected_ids = [record["id"] for record in self.expected]

    def patch_bytes(self, track_id, raw):
        """按原始字节发送 PATCH 请求体（可含空体或非 UTF-8 字节）。"""
        status, headers, body = self.server.raw_request(
            "PATCH", f"/api/tracks/{track_id}", body=raw,
            content_type="application/json",
        )
        return status, headers, body

    def assert_library_unchanged(self):
        """失败后列表的标识、完整资料、数量与次序都与提交前一致。"""
        tracks = self.list_tracks()
        self.assertEqual(
            [record["id"] for record in tracks], self.expected_ids,
            "失败后曲目标识或次序发生变化",
        )
        self.assertEqual(len(tracks), len(self.expected), "失败后记录数量发生变化")
        self.assertEqual(tracks, self.expected, "失败后曲目资料发生变化")

    def assert_malformed_json_rejected(self, raw):
        """无法解析的请求体：400、完整可读的 JSON、只报请求体不是有效 JSON。"""
        status, headers, body = self.patch_bytes(self.track_id, raw)
        self.assertEqual(status, 400, body)
        # 响应完整可读：Content-Type 是 JSON，Content-Length 与实际字节一致，
        # 体可以整体解析（连接没有被突然断开）。
        self.assertTrue(
            headers["Content-Type"].startswith("application/json"),
            headers["Content-Type"],
        )
        self.assertEqual(
            int(headers["Content-Length"]), len(body),
            "响应在传输完成前被截断（连接突然断开）",
        )
        parsed = json.loads(body.decode("utf-8"))
        self.assertEqual(parsed, {"error": "请求体不是有效的 JSON"})
        self.assert_library_unchanged()

    def assert_non_object_rejected(self, raw):
        """可解析但非对象的请求体：400、要求 JSON 对象、field 为 null。"""
        status, headers, body = self.patch_bytes(self.track_id, raw)
        self.assertEqual(status, 400, body)
        self.assertTrue(
            headers["Content-Type"].startswith("application/json"),
            headers["Content-Type"],
        )
        self.assertEqual(int(headers["Content-Length"]), len(body))
        parsed = json.loads(body.decode("utf-8"))
        self.assertEqual(parsed["error"], "请求体必须是 JSON 对象")
        # 不把问题归给名称、时长等某个字段。
        self.assertIsNone(parsed["field"])
        self.assertEqual(set(parsed), {"error", "field"})
        self.assert_library_unchanged()


class EditMalformedJsonBodyTest(_BadRequestBodyFixture):
    """目标曲目存在时，无法解析的请求体一律 400，且不保存任何内容。"""

    # (说明, 原始字节)：空体、缺少结尾、夹多余文字、非 UTF-8 内容。
    MALFORMED_BODIES = [
        ("empty_body", b""),
        ("truncated_object", b'{"title":'),
        ("truncated_array_value", b'{"tags":["\xe6\xb0\x91\xe8\xb0\xa3"]'),
        ("trailing_chinese_junk", b'{"duration":12}\xe5\xa4\x9a\xe4\xbd\x99'),
        ("leading_chinese_junk", b'\xe5\xba\x8f{"duration":12}'),
        ("two_json_documents", b'{"duration":12}{"duration":13}'),
        ("invalid_utf8_in_string", b'{"title":"\xff\xfe"}'),
        ("lone_invalid_byte", b"\xff"),
        ("truncated_utf8_sequence", b'{"description":"\xe5\xa4'),
    ]

    def test_malformed_bodies_return_400_readable_json(self):
        for label, raw in self.MALFORMED_BODIES:
            with self.subTest(body=label):
                self.assert_malformed_json_rejected(raw)

    def test_response_is_complete_json_not_dropped_connection(self):
        # 每种畸形体都必须拿到完整响应，不能出现连接突然断开。
        for label, raw in self.MALFORMED_BODIES:
            with self.subTest(body=label):
                status, headers, body = self.patch_bytes(self.track_id, raw)
                self.assertEqual(status, 400)
                self.assertEqual(int(headers["Content-Length"]), len(body))
                self.assertTrue(body, "空响应无法告诉调用者请求体不是有效 JSON")
                json.loads(body.decode("utf-8"))

    def test_json_error_is_distinct_from_object_type_error(self):
        # 调用者必须能区分“请求体格式错误”和“资料类型错误”：
        # 前者只有 error，后者额外带 field=null。
        status, _, malformed = self.patch_bytes(self.track_id, b'{"title":')
        self.assertEqual(status, 400)
        self.assertEqual(
            json.loads(malformed), {"error": "请求体不是有效的 JSON"}
        )
        status, _, non_object = self.patch_bytes(self.track_id, b'["x"]')
        self.assertEqual(status, 400)
        self.assertEqual(
            json.loads(non_object),
            {"error": "请求体必须是 JSON 对象", "field": None},
        )

    def test_no_success_even_when_body_text_mentions_fields(self):
        # 畸形体里即使写着看似合法的字段内容，也不能出现保存成功。
        for label, raw in self.MALFORMED_BODIES:
            with self.subTest(body=label):
                status, _, _ = self.patch_bytes(self.track_id, raw)
                self.assertEqual(status, 400)
        self.assertEqual(self.track_by_id(self.track_id), self.track_v1)

    def test_rich_text_and_both_versions_kept_after_all_failures(self):
        for _, raw in self.MALFORMED_BODIES:
            self.assert_malformed_json_rejected(raw)
        tracks = {record["id"]: record for record in self.list_tracks()}
        # 目标曲目与同一来源的独立版本各自保持原样：说明中的中文与空行、
        # 标签的完整文字和先后关系都在。
        self.assertEqual(tracks[self.track_v1["id"]], self.track_v1)
        self.assertEqual(tracks[self.track_v2["id"]], self.track_v2)
        self.assertEqual(tracks[self.bystander["id"]], self.bystander)
        target = tracks[self.track_id]
        self.assertEqual(
            target["description"], "第一段说明\n\n第二段：含中文与标点！\n\n"
        )
        self.assertEqual(
            target["tags"],
            ["民谣", "现场  录音", "逗号,标签", "顿号、标签", "多行\n标签"],
        )


class EditNonObjectJsonBodyTest(_BadRequestBodyFixture):
    """能解析成 JSON 但顶层不是对象：400 且 field=null，不保存任何内容。"""

    NON_OBJECT_BODIES = [
        ("array_with_mixed_items", b'["\xe4\xb8\x8d\xe5\xba\x94\xe4\xbf\x9d\xe5\xad\x98", 1]'),
        ("empty_array", b"[]"),
        ("string", b'"\xe4\xb8\x8d\xe5\xba\x94\xe4\xbf\x9d\xe5\xad\x98\xe7\x9a\x84\xe5\x90\x8d\xe7\xa7\xb0"'),
        ("empty_string", b'""'),
        ("integer", b"42"),
        ("decimal", b"12.5"),
        ("negative_number", b"-3"),
        ("true", b"true"),
        ("false", b"false"),
        ("null", b"null"),
    ]

    def test_non_object_bodies_return_400_with_null_field(self):
        for label, raw in self.NON_OBJECT_BODIES:
            with self.subTest(body=label):
                self.assert_non_object_rejected(raw)

    def test_error_is_about_object_shape_not_any_field(self):
        for label, raw in self.NON_OBJECT_BODIES:
            with self.subTest(body=label):
                status, _, body = self.patch_bytes(self.track_id, raw)
                self.assertEqual(status, 400)
                parsed = json.loads(body)
                self.assertIn("JSON 对象", parsed["error"])
                for field_label in ("名称", "来源", "时长", "说明", "标签", "封面"):
                    self.assertNotIn(field_label, parsed["error"])
                self.assertIsNone(parsed["field"])

    def test_bare_string_is_not_saved_as_title(self):
        self.assert_non_object_rejected(b'"\xe5\xa4\x9c\xe8\x88\xaa\xef\xbc\x88\xe6\x96\xb0\xe7\x89\x88\xef\xbc\x89"')
        self.assertEqual(
            self.track_by_id(self.track_id)["title"], self.track_v1["title"]
        )

    def test_bare_array_is_not_saved_as_tags(self):
        self.assert_non_object_rejected(b'["\xe6\x96\xb0\xe6\xa0\x87\xe7\xad\xbeA", "\xe6\x96\xb0\xe6\xa0\x87\xe7\xad\xbeB"]')
        self.assertEqual(
            self.track_by_id(self.track_id)["tags"], self.track_v1["tags"]
        )

    def test_bare_number_is_not_saved_as_duration(self):
        self.assert_non_object_rejected(b"300")
        self.assertEqual(
            self.track_by_id(self.track_id)["duration"],
            self.track_v1["duration"],
        )

    def test_bare_null_clears_nothing(self):
        self.assert_non_object_rejected(b"null")
        self.assertEqual(self.track_by_id(self.track_id), self.track_v1)

    def test_both_versions_kept_after_all_non_object_failures(self):
        for _, raw in self.NON_OBJECT_BODIES:
            self.assert_non_object_rejected(raw)
        tracks = {record["id"]: record for record in self.list_tracks()}
        self.assertEqual(tracks[self.track_v1["id"]], self.track_v1)
        self.assertEqual(tracks[self.track_v2["id"]], self.track_v2)
        self.assertEqual(tracks[self.bystander["id"]], self.bystander)


class EditInvalidBodyPersistenceTest(_BadRequestBodyFixture):
    """失败后资料保留、失败内容不补入，以及空体/空对象/部分修改的对照。"""

    def test_rejected_edits_are_not_merged_into_later_valid_patch(self):
        # 畸形体与裸字符串都试图改名/改时长，必须全部被拒。
        self.assert_malformed_json_rejected(
            b'{"title":"\xe4\xb8\x8d\xe5\xba\x94\xe4\xbf\x9d\xe5\xad\x98\xe7\x9a\x84\xe5\x90\x8d\xe7\xa7\xb0","duration":300,'
        )
        self.assert_non_object_rejected(
            b'"\xe4\xb9\x9f\xe4\xb8\x8d\xe5\xba\x94\xe4\xbf\x9d\xe5\xad\x98\xe7\x9a\x84\xe5\x90\x8d\xe7\xa7\xb0"'
        )
        # 之后的合法请求只提交标签：被拒绝的名称、时长不会自动补入，
        # 实际保存只采用本次明确提交的资料。
        status, body = self.patch(self.track_id, {"tags": ["只有本次明确提交的标签"]})
        self.assertEqual(status, 200, body)
        current = self.track_by_id(self.track_id)
        self.assertEqual(current["tags"], ["只有本次明确提交的标签"])
        self.assertEqual(current["title"], self.track_v1["title"])
        self.assertEqual(current["duration"], self.track_v1["duration"])
        self.assertEqual(current["source"], self.track_v1["source"])
        self.assertEqual(current["cover_url"], self.track_v1["cover_url"])
        self.assertEqual(current["description"], self.track_v1["description"])
        tracks = {record["id"]: record for record in self.list_tracks()}
        self.assertEqual(tracks[self.track_v2["id"]], self.track_v2)
        self.assertEqual(tracks[self.bystander["id"]], self.bystander)

    def test_empty_body_is_400_but_empty_object_is_200_and_keeps_record(self):
        # 空请求体与空对象必须有各自明确的结果。
        status, _, body = self.patch_bytes(self.track_id, b"")
        self.assertEqual(status, 400)
        self.assertEqual(
            json.loads(body), {"error": "请求体不是有效的 JSON"}
        )
        status, body = self.patch(self.track_id, {})
        self.assertEqual(status, 200, body)
        self.assertEqual(body, self.track_v1)
        self.assertEqual(self.track_by_id(self.track_id), self.track_v1)

    def test_partial_payload_after_failures_changes_only_submitted_field(self):
        self.assert_malformed_json_rejected(b'{"duration":')
        self.assert_non_object_rejected(b"true")
        status, body = self.patch(self.track_id, {"description": "新的说明"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["id"], self.track_id)
        self.assertEqual(body["description"], "新的说明")
        # 未提交的字段保留原值。
        self.assertEqual(body["title"], self.track_v1["title"])
        self.assertEqual(body["source"], self.track_v1["source"])
        self.assertEqual(body["duration"], self.track_v1["duration"])
        self.assertEqual(body["cover_url"], self.track_v1["cover_url"])
        self.assertEqual(body["tags"], self.track_v1["tags"])
        self.assertEqual(self.track_by_id(self.track_id), body)

    def test_list_readable_and_track_editable_after_every_failure(self):
        for _, raw in EditMalformedJsonBodyTest.MALFORMED_BODIES:
            status, _, _ = self.patch_bytes(self.track_id, raw)
            self.assertEqual(status, 400)
        for _, raw in EditNonObjectJsonBodyTest.NON_OBJECT_BODIES:
            status, _, _ = self.patch_bytes(self.track_id, raw)
            self.assertEqual(status, 400)
        # 失败之后列表仍能正常读取。
        self.assertEqual(self.list_tracks(), self.expected)
        # 已有曲目仍能接受合法编辑。
        status, body = self.patch(self.track_id, {"duration": 0})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["duration"], 0)
        self.assertEqual(body["title"], self.track_v1["title"])


class EditNonexistentIdBodyOrderingTest(ServerTestCase):
    """不存在的普通数字标识：先判请求体格式，能解析再返回 404。"""

    def setUp(self):
        super().setUp()
        self.existing = self.create_track(
            title="夜航",
            source="/music/yehang.flac",
            description="说明\n\n第二段",
            tags=["民谣"],
        )
        self.missing_id = self.existing["id"] + 1000

    def patch_bytes(self, raw):
        return self.server.raw_request(
            "PATCH", f"/api/tracks/{self.missing_id}", body=raw,
            content_type="application/json",
        )

    def test_unparseable_body_reports_json_error_before_not_found(self):
        for raw in (
            b"",
            b'{"title":',
            b'{"x":}\xff',
            b'{"title":"\xff\xfe"}',
            b"\xff",
        ):
            with self.subTest(raw=raw):
                status, headers, body = self.patch_bytes(raw)
                self.assertEqual(status, 400, body)
                self.assertEqual(int(headers["Content-Length"]), len(body))
                self.assertEqual(
                    json.loads(body), {"error": "请求体不是有效的 JSON"}
                )

    def test_parseable_body_returns_404_even_when_top_level_not_object(self):
        # 请求体能够解析时，即使顶层不是对象，也只报曲目不存在，
        # 不继续报告字段/类型错误。
        for raw in (b"{}", b'{"title":"x"}', b"[]", b'"x"', b"42", b"true", b"null"):
            with self.subTest(raw=raw):
                status, headers, body = self.patch_bytes(raw)
                self.assertEqual(status, 404, body)
                self.assertEqual(int(headers["Content-Length"]), len(body))
                parsed = json.loads(body)
                self.assertEqual(
                    parsed, {"error": f"曲目 #{self.missing_id} 不存在"}
                )
                self.assertNotIn("field", parsed)

    def test_not_found_response_is_complete_json(self):
        status, headers, body = self.patch_bytes(b'{"title":"x"}')
        self.assertEqual(status, 404)
        self.assertTrue(
            headers["Content-Type"].startswith("application/json"),
            headers["Content-Type"],
        )
        json.loads(body)

    def test_probes_leave_real_record_untouched_and_editable(self):
        for raw in (b"", b'{"title":', b"[]", b"null", b'{"title":"x"}'):
            self.patch_bytes(raw)
        self.assertEqual(self.list_tracks(), [self.existing])
        # 真实存在的曲目仍能接受合法编辑。
        status, body = self.patch(
            self.existing["id"], {"title": "夜航（修订）"}
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["title"], "夜航（修订）")
        self.assertEqual(body["description"], "说明\n\n第二段")
        self.assertEqual(body["tags"], ["民谣"])


# ---------------------------------------------------------------------------
# 曲库在服务启动前就已经存在：旧表只有标识与名称两列，来源、时长、封面
# 地址、说明和标签都尚未保存。下列用例先在数据目录里建好这种旧曲库，再
# 启动服务，固定当前服务对“打开旧曲库”的兼容行为。


class _PreexistingLegacyLibraryFixture(ServerTestCase):
    """启动前已存在的旧曲库：标识不从 1 开始且中间有空缺，含同名记录，
    其中一条名称带内部空格、连续空行、引号与尖括号。"""

    DUPLICATE_TITLE = "回声 旧曲"
    MULTILINE_TITLE = (
        "夜航\n\n  现场  版\n“引号”与“双引号”"
        "<tag>看起来像网页标签"
    )
    # 标识 3、7、12：不从 1 开始，4-6、8-11 都是空缺，也没有 1、2。
    LEGACY_ROWS = [
        (3, DUPLICATE_TITLE),
        (7, DUPLICATE_TITLE),
        (12, MULTILINE_TITLE),
    ]
    LEGACY_IDS = [3, 7, 12]

    def setUp(self):
        # 不调用父类 setUp：先在数据目录写好旧表，再带着旧曲库启动服务。
        self.server = self.make_server(seeded_rows=self.LEGACY_ROWS)
        self.addCleanup(self.server.close)

    def expected_legacy(self, track_id):
        title = dict(self.LEGACY_ROWS)[track_id]
        return {
            "id": track_id,
            "title": title,
            "source": None,
            "duration": None,
            "cover_url": "",
            "description": "",
            "tags": [],
        }

    def expected_legacy_records(self):
        return [self.expected_legacy(track_id) for track_id in self.LEGACY_IDS]


class PreexistingLegacyLibraryApiTest(_PreexistingLegacyLibraryFixture):
    """打开启动前已存在的旧曲库：曲目列表接口原样提供旧记录。"""

    def test_list_keeps_ids_titles_count_and_ascending_order(self):
        tracks = self.list_tracks()
        # 标识、名称与记录数量保持不变，仍按标识升序；不重新编号。
        self.assertEqual([t["id"] for t in tracks], self.LEGACY_IDS)
        self.assertEqual(len(tracks), 3)
        self.assertEqual(tracks, self.expected_legacy_records())

    def test_duplicate_titles_remain_two_separate_records(self):
        tracks = self.list_tracks()
        same_name = [t for t in tracks if t["title"] == self.DUPLICATE_TITLE]
        # 名称相同的两条记录各自保留，不会被合并成一条。
        self.assertEqual([t["id"] for t in same_name], [3, 7])

    def test_multiline_title_is_not_trimmed_merged_or_rewritten(self):
        # 中文、内部空格、连续空行、引号与尖括号都按旧曲库原文读出。
        self.assertEqual(
            self.track_by_id(12)["title"], self.MULTILINE_TITLE
        )
        self.assertNotIn(
            "夜航  现场  版",
            self.track_by_id(12)["title"],
            "连续空行不能被合并",
        )

    def test_missing_fields_use_legacy_shape(self):
        for track_id in self.LEGACY_IDS:
            record = self.track_by_id(track_id)
            # 来源、时长为 null；封面地址与说明为空字符串；标签为空数组。
            self.assertIsNone(record["source"], f"#{track_id} 来源应为 null")
            self.assertIsNone(record["duration"], f"#{track_id} 时长应为 null")
            self.assertEqual(record["cover_url"], "")
            self.assertEqual(record["description"], "")
            self.assertEqual(record["tags"], [])

    def test_unknown_duration_is_not_zero(self):
        for record in self.list_tracks():
            self.assertIsNone(record["duration"])
            self.assertNotEqual(record["duration"], 0)

    def test_missing_source_is_not_synthesized_from_title_or_id(self):
        # 缺失来源保持 null，不能凭名称或标识自动生成任何来源文字。
        for record in self.list_tracks():
            self.assertIsNone(record["source"])
            self.assertNotEqual(record["source"], record["title"])
            self.assertNotEqual(record["source"], str(record["id"]))

    def test_gaps_and_unknown_ids_are_not_filled_in(self):
        # 空缺标识与末尾之后的标识都不存在，不会补出额外曲目。
        for missing_id in (1, 2, 4, 5, 6, 8, 11, 13):
            status, body = self.patch(missing_id, {"description": "不应写入"})
            self.assertEqual(status, 404, f"标识 #{missing_id} 不应存在")
        # 失败探测没有新增任何记录。
        self.assertEqual(
            [t["id"] for t in self.list_tracks()], self.LEGACY_IDS
        )

    def test_records_still_readable_after_service_reopen(self):
        # 重新打开同一数据目录：旧曲库仍是原样，数量与标识不变。
        self.restart_server()
        self.assertEqual(self.list_tracks(), self.expected_legacy_records())


class PreexistingLegacyLibraryHomeTest(_PreexistingLegacyLibraryFixture):
    """打开启动前已存在的旧曲库：首页列表正常展示旧记录与缺失占位。"""

    def test_home_lists_all_records_in_id_order_with_title_lines(self):
        page = self.get_home()
        # 首页同样提供全部原有记录，按标识升序，名称分行保留。
        self.assertEqual(parse_listed_tracks(page), [
            (3, self.DUPLICATE_TITLE),
            (7, self.DUPLICATE_TITLE),
            (12, self.MULTILINE_TITLE),
        ])

    def test_home_shows_special_title_as_plain_text_with_line_breaks(self):
        page = self.get_home()
        cards = parse_listed_track_cards(page)
        self.assertEqual(set(cards), set(self.LEGACY_IDS))
        # 名称读回仍是旧曲库原文：内部空格、连续空行与引号都在。
        self.assertEqual(cards[12]["title"], self.MULTILINE_TITLE)
        listing = TRACK_LIST_RE.search(page).group(1)
        # 名称按已有规则分行显示（white-space:pre-wrap 保留换行）。
        self.assertIn("夜航\n\n  现场  版", listing)
        # 尖括号与形似网页标签的文字按普通文字转义，不生成页面元素。
        self.assertIn("&lt;tag&gt;看起来像网页标签", listing)
        self.assertNotIn("<tag>看起来像网页标签", listing)

    def test_home_shows_unfilled_placeholders_and_no_tags(self):
        page = self.get_home()
        cards = parse_listed_track_cards(page)
        for track_id in self.LEGACY_IDS:
            # 旧记录尚未填写的来源、时长、封面与说明显示为未填写。
            self.assertEqual(
                listed_field(cards, track_id, "来源"),
                ("placeholder", "未填写"),
            )
            self.assertEqual(
                listed_field(cards, track_id, "时长"),
                ("placeholder", "未填写"),
            )
            self.assertEqual(
                listed_field(cards, track_id, "封面地址"),
                ("placeholder", "未填写"),
            )
            self.assertEqual(
                listed_field(cards, track_id, "说明"),
                ("placeholder", "未填写"),
            )
            # 标签显示为“无”，且没有任何标签徽标。
            self.assertEqual(
                listed_field(cards, track_id, "标签"),
                ("placeholder", "无"),
            )
            self.assertEqual(cards[track_id]["tags"], [])

    def test_home_unknown_duration_is_not_shown_as_zero_seconds(self):
        page = self.get_home()
        durations = parse_listed_durations(page)
        self.assertEqual(durations, ["未填写", "未填写", "未填写"])
        self.assertNotIn("0 秒", page)

    def test_home_provides_edit_links_for_legacy_records(self):
        page = self.get_home()
        for track_id in self.LEGACY_IDS:
            self.assertIn(f'/tracks/{track_id}/edit', page)


class PreexistingLegacyEditFlowTest(_PreexistingLegacyLibraryFixture):
    """打开旧曲目的编辑页：保留来源空白，只补合法时长与说明后继续整理。"""

    EDITED_ID = 7
    OTHER_IDS = [3, 12]
    NEW_DESCRIPTION = "本次补写的说明\n第二行保留"

    def test_edit_page_opens_with_original_title_and_empty_fields(self):
        page = self.get_edit_page(self.EDITED_ID)
        self.assert_form_values(
            page,
            title=self.DUPLICATE_TITLE,
            source="",
            duration="",
            cover_url="",
            description="",
        )
        # 旧记录没有标签：只有一个可新增的空标签框。
        self.assert_tag_boxes(page, [""])

    def test_save_keeps_source_blank_and_uses_same_id(self):
        page = self.get_edit_page(self.EDITED_ID)
        fields = self.edit_fields_from_rendered_page(page)
        fields = self.form_with_field(fields, "duration", "243.5")
        fields = self.form_with_field(
            fields, "description", self.NEW_DESCRIPTION.replace("\n", "\r\n")
        )
        # 名称与来源都未改：名称仍是旧曲库原文，来源继续留空。
        status, headers, _ = self.post_edit_form(self.EDITED_ID, fields)
        self.assertEqual(status, 303)
        self.assertEqual(
            headers["Location"],
            f"/?highlight={self.EDITED_ID}&edited=1",
        )

        tracks = self.list_tracks()
        self.assertEqual([t["id"] for t in tracks], self.LEGACY_IDS)
        edited = self.track_by_id(self.EDITED_ID)
        # 继续使用原标识，原名称保留；来源仍缺失（不自动生成），
        # 本次只补上合法时长与说明，封面与标签仍按旧记录为空。
        self.assertEqual(edited, {
            "id": self.EDITED_ID,
            "title": self.DUPLICATE_TITLE,
            "source": None,
            "duration": 243.5,
            "cover_url": "",
            "description": self.NEW_DESCRIPTION,
            "tags": [],
        })

    def test_saved_content_readable_from_reopened_edit_page_and_home(self):
        self.save_edited_record()
        # 重新打开编辑页能读到刚保存的内容，来源框仍为空。
        page = self.get_edit_page(self.EDITED_ID)
        self.assert_form_values(
            page,
            title=self.DUPLICATE_TITLE,
            source="",
            duration="243.5",
            cover_url="",
            description=self.NEW_DESCRIPTION,
        )
        self.assert_tag_boxes(page, [""])
        # 首页：来源仍未填写，时长显示秒数，说明展示补写内容，
        # 封面仍未填写，标签仍为无。
        home = self.get_home()
        cards = parse_listed_track_cards(home)
        self.assertEqual(
            listed_field(cards, self.EDITED_ID, "来源"),
            ("placeholder", "未填写"),
        )
        self.assertEqual(
            listed_field(cards, self.EDITED_ID, "时长"),
            ("text", "243.5 秒"),
        )
        self.assertEqual(
            listed_field(cards, self.EDITED_ID, "封面地址"),
            ("placeholder", "未填写"),
        )
        self.assertEqual(
            listed_field(cards, self.EDITED_ID, "说明"),
            ("text", self.NEW_DESCRIPTION),
        )
        self.assertEqual(
            listed_field(cards, self.EDITED_ID, "标签"),
            ("placeholder", "无"),
        )

    def test_saved_content_survives_service_reopen(self):
        self.save_edited_record()
        # 重新打开同一曲库后，列表接口与编辑页仍能读到已保存内容。
        self.restart_server()
        edited = self.track_by_id(self.EDITED_ID)
        self.assertEqual(edited["duration"], 243.5)
        self.assertEqual(edited["description"], self.NEW_DESCRIPTION)
        self.assertIsNone(edited["source"])
        page = self.get_edit_page(self.EDITED_ID)
        self.assert_form_values(
            page, duration="243.5", description=self.NEW_DESCRIPTION, source=""
        )

    def test_other_legacy_records_stay_untouched(self):
        self.save_edited_record()
        # 另一条同名旧记录与多行名称旧记录都保持旧记录原状。
        for other_id in self.OTHER_IDS:
            self.assertEqual(
                self.track_by_id(other_id), self.expected_legacy(other_id)
            )

    def save_edited_record(self):
        """保留来源空白，只补合法时长与说明，保存这条旧曲目。"""
        page = self.get_edit_page(self.EDITED_ID)
        fields = self.edit_fields_from_rendered_page(page)
        fields = self.form_with_field(fields, "duration", "243.5")
        fields = self.form_with_field(
            fields, "description", self.NEW_DESCRIPTION.replace("\n", "\r\n")
        )
        status, _, resp = self.post_edit_form(self.EDITED_ID, fields)
        self.assertEqual(status, 303, resp[:500])


class PreexistingLegacyBlankTitleFailureTest(_PreexistingLegacyLibraryFixture):
    """整理旧曲目时名称变成纯空白：400 留错，改名后采用错误页填写。"""

    EDITED_ID = 3
    OTHER_IDS = [7, 12]
    NEW_DESCRIPTION = "本次补写的说明\n第二行保留"

    def submit_blank_title_form(self):
        # 名称改成纯空白（空格、制表符与空行），来源仍留空，
        # 同时填写合法的时长与说明。
        fields = self.edit_form_fields(
            title="  \t\r\n ",
            source="",
            duration="300",
            cover_url="",
            description=self.NEW_DESCRIPTION.replace("\n", "\r\n"),
        )
        status, _, page = self.post_edit_form(self.EDITED_ID, fields)
        self.assertEqual(status, 400)
        return page

    def assert_title_error(self, page):
        banner = BANNER_ERROR_RE.search(page)
        self.assertIsNotNone(banner, "页面应显示保存失败提示")
        self.assertIn("名称", strip_tags(banner.group(1)))
        field_errors = [strip_tags(raw) for raw in FIELD_ERROR_RE.findall(page)]
        self.assertTrue(
            any("名称" in text for text in field_errors),
            f"名称字段旁应指出错误，实际：{field_errors}",
        )
        self.assertIsNone(BANNER_SUCCESS_RE.search(page))

    def test_blank_title_returns_400_and_keeps_legacy_record(self):
        page = self.submit_blank_title_form()
        self.assert_title_error(page)
        # 原曲目的名称、缺失来源及其他资料保持原样。
        self.assertEqual(
            self.track_by_id(self.EDITED_ID),
            self.expected_legacy(self.EDITED_ID),
        )
        for other_id in self.OTHER_IDS:
            self.assertEqual(
                self.track_by_id(other_id), self.expected_legacy(other_id)
            )
        self.assertEqual(
            [t["id"] for t in self.list_tracks()], self.LEGACY_IDS
        )

    def test_error_page_keeps_submitted_duration_and_description(self):
        page = self.submit_blank_title_form()
        # 本次填写的名称空白、时长与说明都留在错误页中，不被旧值替换。
        self.assertEqual(parse_title_box(page), "  \t\n ")
        self.assertEqual(parse_source_box(page), "")
        self.assert_form_values(page, duration="300")
        self.assertEqual(parse_description_box(page), self.NEW_DESCRIPTION)
        self.assertEqual(parse_cover_box(page), "")

    def test_fix_only_title_saves_error_page_values_without_new_record(self):
        failed_page = self.submit_blank_title_form()
        # 只修正名称，错误页里保留的时长与说明按回填内容再次提交。
        retry_fields = self.edit_fields_from_rendered_page(failed_page)
        retry_fields = self.form_with_field(
            retry_fields, "title", f"  {self.DUPLICATE_TITLE}（整理）  "
        )
        retry_fields = [
            (name, value.replace("\n", "\r\n"))
            if name in ("description", "tags") else (name, value)
            for name, value in retry_fields
        ]
        status, headers, _ = self.post_edit_form(
            self.EDITED_ID, retry_fields
        )
        self.assertEqual(status, 303)
        self.assertEqual(
            headers["Location"],
            f"/?highlight={self.EDITED_ID}&edited=1",
        )

        tracks = self.list_tracks()
        # 不新增曲目，标识与数量保持旧曲库原样。
        self.assertEqual([t["id"] for t in tracks], self.LEGACY_IDS)
        edited = self.track_by_id(self.EDITED_ID)
        # 采用错误页里的填写：名称只裁掉首尾空白，时长与说明是上次填写，
        # 来源继续缺失，封面与标签仍为空。
        self.assertEqual(edited, {
            "id": self.EDITED_ID,
            "title": f"{self.DUPLICATE_TITLE}（整理）",
            "source": None,
            "duration": 300,
            "cover_url": "",
            "description": self.NEW_DESCRIPTION,
            "tags": [],
        })
        # 重新打开的编辑页与列表接口读到的内容一致。
        page = self.get_edit_page(self.EDITED_ID)
        self.assert_form_values(
            page,
            title=f"{self.DUPLICATE_TITLE}（整理）",
            source="",
            duration="300",
            description=self.NEW_DESCRIPTION,
        )
        # 另一条同名旧记录与多行名称旧记录不受影响。
        for other_id in self.OTHER_IDS:
            self.assertEqual(
                self.track_by_id(other_id), self.expected_legacy(other_id)
            )


# ---------------------------------------------------------------------------
# 首页关键词查找（GET / 的 q 参数）：在名称、来源、说明与每个标签的完整
# 文字中查找连续文字，任意一项命中即显示；封面地址与时长不参加搜索。

SEARCH_INPUT_RE = re.compile(
    r'<input type="text" id="f-search" name="q"[^>]*?value="(.*?)"[^>]*?>',
    re.DOTALL,
)
SEARCH_SUMMARY_RE = re.compile(
    r'<p class="search-summary">(.*?)</p>', re.DOTALL
)
SEARCH_CLEAR_RE = re.compile(
    r'<a class="search-clear" href="/">(.*?)</a>', re.DOTALL
)


def parse_search_box(page):
    """提取首页关键词查找框中保留的关键词（已还原 HTML 转义）。"""
    match = SEARCH_INPUT_RE.search(page)
    assert match is not None, "页面中找不到关键词查找框"
    return html.unescape(match.group(1))


def parse_search_summary(page):
    """提取搜索结果统计文字（找到的数量与曲库总数）。"""
    match = SEARCH_SUMMARY_RE.search(page)
    assert match is not None, "页面中没有搜索结果统计"
    return strip_tags(match.group(1))


def parse_clear_search_link(page):
    """提取“清除搜索”链接文字；没有清除入口时返回 None。"""
    match = SEARCH_CLEAR_RE.search(page)
    return strip_tags(match.group(1)) if match is not None else None


class HomeSearchTestCase(ServerTestCase):
    """关键词查找用例的公共工具：按关键词打开首页并读取列表。"""

    def home_page(self, keyword=None):
        query = "" if keyword is None else "?" + urlencode({"q": keyword})
        status, _, page = self.server.get_page(f"/{query}")
        assert status == 200, f"打开首页失败：{status}"
        return page

    def listed_ids(self, page):
        return [track_id for track_id, _ in parse_listed_tracks(page)]


class HomeSearchFieldMatchTest(HomeSearchTestCase):
    """名称、来源、说明或任一标签的完整文字包含关键词即显示该曲目。"""

    def setUp(self):
        super().setUp()
        self.by_title = self.create_track(
            title="夜航（现场版）",
            source="/music/yehang-live.flac",
            description="录音室版本",
            tags=["民谣"],
        )
        self.by_source = self.create_track(
            title="海港",
            source="/music/现场录音/haigang.flac",
            tags=["摇滚"],
        )
        self.by_description = self.create_track(
            title="远山",
            source="/music/yuanshan.flac",
            description="这是一段现场采样的素材",
        )
        self.by_tag = self.create_track(
            title="星图",
            source="/music/xingtu.flac",
            tags=["纯音乐", "现场版精选"],
        )
        self.unrelated = self.create_track(
            title="晨跑",
            source="/music/chenpao.flac",
            description="节奏轻快",
            tags=["运动"],
        )

    def test_keyword_matches_any_single_field(self):
        page = self.home_page("现场")
        ids = self.listed_ids(page)
        # 名称、来源、说明、标签各自命中的四条都显示，未命中的不显示。
        self.assertEqual(ids, [
            self.by_title["id"],
            self.by_source["id"],
            self.by_description["id"],
            self.by_tag["id"],
        ])
        # 结果按曲目标识升序，并显示找到的数量与曲库总数。
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(
            parse_search_summary(page),
            "找到 4 首符合关键词“现场”的曲目（曲库共 5 首）。",
        )
        # 查找框保留实际采用的关键词。
        self.assertEqual(parse_search_box(page), "现场")

    def test_results_keep_listing_display_and_edit_entry(self):
        page = self.home_page("现场")
        cards = parse_listed_track_cards(page)
        # 命中的曲目沿用列表原有的资料展示。
        self.assertEqual(
            cards[self.by_title["id"]]["title"], "夜航（现场版）"
        )
        self.assertEqual(
            cards[self.by_tag["id"]]["tags"], ["纯音乐", "现场版精选"]
        )
        kind, value = listed_field(cards, self.by_source["id"], "来源")
        self.assertEqual((kind, value), ("text", "/music/现场录音/haigang.flac"))
        # 每条结果仍提供编辑入口。
        for track_id in self.listed_ids(page):
            self.assertIn(f'href="/tracks/{track_id}/edit"', page)


class HomeSearchMatchingRulesTest(HomeSearchTestCase):
    """匹配规则：去首尾空白、英文不区分大小写、连续文字、特殊符号按
    普通文字、不跨字段或跨标签拼接。"""

    def test_english_letters_are_case_insensitive(self):
        track = self.create_track(
            title="夜航（Live版）", source="/music/live.flac"
        )
        for keyword in ("live", "LIVE", "Live"):
            page = self.home_page(keyword)
            self.assertEqual(self.listed_ids(page), [track["id"]])

    def test_chinese_matches_literal_text(self):
        track = self.create_track(title="夜航（现场版）", source="/music/a.flac")
        page = self.home_page("现场")
        self.assertEqual(self.listed_ids(page), [track["id"]])
        # 连续文字而非整项相等：名称只是包含关键词，并不要求相等。
        self.assertNotEqual(track["title"], "现场")

    def test_keyword_trimmed_but_inner_space_is_content(self):
        track = self.create_track(title="夜航 现场", source="/music/b.flac")
        # 首尾空白被去掉后再查找，页面保留实际采用的关键词。
        page = self.home_page("  夜航 现场  ")
        self.assertEqual(self.listed_ids(page), [track["id"]])
        self.assertEqual(parse_search_box(page), "夜航 现场")
        # 内部空格是搜索内容：两个空格与名称中的一个空格不匹配。
        page = self.home_page("夜航  现场")
        self.assertIn("没有符合关键词", page)

    def test_special_characters_are_plain_text(self):
        track = self.create_track(
            title="100%_纯净 \"'<引号>'", source="/music/c.flac"
        )
        other = self.create_track(title="普通曲目", source="/music/d.flac")
        # 百分号与下划线不是通配符：只命中真正包含这段文字的曲目。
        page = self.home_page("%_")
        self.assertEqual(self.listed_ids(page), [track["id"]])
        # 单独的 % 不能匹配所有曲目。
        page = self.home_page("%")
        self.assertEqual(self.listed_ids(page), [track["id"]])
        # 引号与尖括号同样按普通文字查找。
        page = self.home_page("\"'<引号>")
        self.assertEqual(self.listed_ids(page), [track["id"]])
        # 输入与结果中的文字按普通文字安全显示。
        page = self.home_page("<script>")
        self.assertIn('value="&lt;script&gt;"', page)
        self.assertEqual(parse_search_box(page), "<script>")
        self.assertEqual(
            parse_search_summary(page),
            "找到 0 首符合关键词“<script>”的曲目（曲库共 2 首）。",
        )

    def test_no_concatenation_across_tags_or_fields(self):
        # 一个标签有“夜”、另一个标签有“航”，不能凑出“夜航”。
        split_tags = self.create_track(
            title="其他", source="/music/e.flac", tags=["夜", "航"]
        )
        # 名称有“夜”、说明有“航”，同样不能跨字段凑出命中。
        split_fields = self.create_track(
            title="夜", source="/music/f.flac", description="航"
        )
        page = self.home_page("夜航")
        self.assertIn("没有符合关键词", page)
        self.assertIsNone(TRACK_LIST_RE.search(page))
        # 同一个标签完整包含关键词才命中。
        page = self.home_page("夜")
        self.assertEqual(
            self.listed_ids(page), [split_tags["id"], split_fields["id"]]
        )


class HomeSearchScopeTest(HomeSearchTestCase):
    """搜索范围：封面地址与时长不参加；旧记录按名称可找；占位提示不是
    资料。"""

    def test_cover_url_and_duration_are_not_searched(self):
        self.create_track(
            title="海港",
            source="/music/haigang.flac",
            cover_url="独特封面文字.jpg",
            duration=243.5,
        )
        for keyword in ("独特封面", "243.5"):
            page = self.home_page(keyword)
            self.assertIn("没有符合关键词", page)

    def test_legacy_record_searchable_by_title_only(self):
        legacy_id = self.server.insert_legacy("旧歌名")
        self.create_track(title="新曲", source="/music/new.flac")
        # 只有名称的旧记录可按名称找到。
        page = self.home_page("旧歌")
        self.assertEqual(self.listed_ids(page), [legacy_id])
        # 旧记录缺失的来源、说明与标签视为没有可匹配的文字。
        page = self.home_page("未填写")
        self.assertIn("没有符合关键词", page)
        page = self.home_page("无")
        self.assertIn("没有符合关键词", page)

    def test_empty_fields_provide_no_matchable_text(self):
        track = self.create_track(
            title="空白资料", source="/music/blank.flac",
            description="", tags=[],
        )
        # 空说明与空标签不产生命中；页面占位文字不被当作资料。
        for keyword in ("未填写", "无", "未知"):
            page = self.home_page(keyword)
            self.assertIn("没有符合关键词", page)
        # 名称本身仍正常命中。
        page = self.home_page("空白")
        self.assertEqual(self.listed_ids(page), [track["id"]])


class HomeSearchEmptyStatesTest(HomeSearchTestCase):
    """无结果、空曲库、留空关键词与清除搜索的页面表现。"""

    def test_no_match_keeps_keyword_and_offers_clear(self):
        self.create_track(title="夜航", source="/music/yh.flac")
        page = self.home_page("不存在的关键词")
        self.assertIn("没有符合关键词", page)
        # 搜索条件保留在查找框中，并提供清除搜索入口。
        self.assertEqual(parse_search_box(page), "不存在的关键词")
        self.assertIsNotNone(parse_clear_search_link(page))
        self.assertEqual(
            parse_search_summary(page),
            "找到 0 首符合关键词“不存在的关键词”的曲目（曲库共 1 首）。",
        )

    def test_empty_library_still_reports_no_tracks(self):
        page = self.home_page("任意")
        self.assertIn("还没有曲目记录", page)

    def test_blank_keyword_means_no_filter(self):
        first = self.create_track(title="甲", source="/music/1.flac")
        second = self.create_track(title="乙", source="/music/2.flac")
        for keyword in ("", "   ", "　"):
            page = self.home_page(keyword)
            # 留空或只含空白等同于不筛选：完整列表与原有顺序，无搜索统计。
            self.assertEqual(
                self.listed_ids(page), [first["id"], second["id"]]
            )
            self.assertIsNone(SEARCH_SUMMARY_RE.search(page))
            self.assertIsNone(parse_clear_search_link(page))

    def test_clear_search_restores_full_list(self):
        first = self.create_track(title="夜航", source="/music/3.flac")
        second = self.create_track(title="海港", source="/music/4.flac")
        page = self.home_page("夜航")
        self.assertEqual(self.listed_ids(page), [first["id"]])
        # 清除搜索（回到不带条件的地址）后恢复完整列表与原有顺序。
        page = self.home_page()
        self.assertEqual(
            self.listed_ids(page), [first["id"], second["id"]]
        )
        self.assertIsNone(SEARCH_SUMMARY_RE.search(page))
        # 首页始终提供关键词查找框。
        self.assertEqual(parse_search_box(page), "")


class HomeSearchSideEffectsTest(HomeSearchTestCase):
    """搜索只改变首页展示：不改写曲目，列表接口仍返回全部记录；同名
    记录与同一来源的多个版本各自独立参加搜索。"""

    def test_search_does_not_change_data_and_api_returns_all(self):
        first = self.create_track(
            title="夜航", source="/music/5.flac", tags=["民谣"]
        )
        second = self.create_track(title="海港", source="/music/6.flac")
        before = self.server.list_tracks()
        self.home_page("夜航")
        # 搜索不新增、不改写任何曲目。
        self.assertEqual(self.server.list_tracks(), before)
        # 曲目列表接口保持返回全部记录。
        self.assertEqual(
            [track["id"] for track in self.server.list_tracks()],
            [first["id"], second["id"]],
        )

    def test_reopening_search_url_shows_current_results(self):
        first = self.create_track(title="夜航", source="/music/7.flac")
        page = self.home_page("航")
        self.assertEqual(self.listed_ids(page), [first["id"]])
        # 重新打开同一搜索结果地址，看到同样条件下的当前结果。
        second = self.create_track(title="航标", source="/music/8.flac")
        page = self.home_page("航")
        self.assertEqual(
            self.listed_ids(page), [first["id"], second["id"]]
        )
        self.assertEqual(
            parse_search_summary(page),
            "找到 2 首符合关键词“航”的曲目（曲库共 2 首）。",
        )

    def test_same_title_and_versions_are_listed_independently(self):
        first = self.create_track(title="夜航", source="/music/9.flac")
        # 名称相同的记录独立参加搜索。
        second = self.create_track(title="夜航", source="/music/10.flac")
        # 同一来源另存的多个版本也各自独立显示。
        status, third = self.server.request("POST", "/api/tracks", {
            "title": "夜航",
            "source": "/music/9.flac",
            "save_as_new_version": True,
        })
        assert status == 201, f"准备数据失败：{status} {third}"
        page = self.home_page("夜航")
        self.assertEqual(
            self.listed_ids(page),
            [first["id"], second["id"], third["id"]],
        )
        self.assertEqual(
            parse_search_summary(page),
            "找到 3 首符合关键词“夜航”的曲目（曲库共 3 首）。",
        )


if __name__ == "__main__":
    unittest.main()
