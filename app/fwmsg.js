// 「允许手机连接.bat」放行防火墙后用它显示中文结果（bat 文件里只放英文，避免乱码）
const ok = process.argv[2] === 'ok';
console.log('');
if (ok) {
  console.log('  已放行：店里同一个 WiFi 下的手机、平板现在可以打开收银系统了。');
  console.log('  打开地址看收银系统黑色窗口里的「平板/手机打开」那一行。');
  console.log('  还是打不开的话，多半是 WiFi 不让设备互相访问（学校/商场 WiFi 常见），');
  console.log('  可以用店里自己的路由器，或者看使用说明里的「外网访问」。');
} else {
  console.log('  没放行成功：请右键这个文件，选「以管理员身份运行」再试一次。');
}
console.log('');
