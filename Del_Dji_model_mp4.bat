@echo off
chcp 65001 >nul

echo ========================================
echo    警告：即将执行批量删除操作
echo ========================================
echo 目标目录: E:\DV\采集建档V2.1\Dji_mp4\目录下的Nomal和Night文件夹内容 
echo 操作: 删除该目录下所有文件（保留子目录）
echo. 
echo 请输入选项：
echo   [ Y ] 确认删除
echo   [ N ] 取消操作
echo ========================================
echo.

set /p choice="您的选择 (Y/N): "

if /I "%choice%"=="Y" goto delete
if /I "%choice%"=="YES" goto delete
goto cancel

:delete
echo.
echo 正在删除文件...
del /Q "E:\DV\采集建档V2.1\Dji_mp4\Nomal\*"
del /Q "E:\DV\采集建档V2.1\Dji_mp4\Night\*"
echo.
echo 删除完成！
goto end

:cancel
echo.
echo 操作已取消，未删除任何文件。

:end
pause